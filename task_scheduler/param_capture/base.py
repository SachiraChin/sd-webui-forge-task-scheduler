"""
Base classes for parameter capture and restoration.

These abstract classes define the interface for capturing parameters from
processing objects and restoring them during task execution.
"""
import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple

from modules import shared
from modules.processing import StableDiffusionProcessing

from ..models import TaskType


# Get extension directory for temp image storage
ext_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BaseParameterCapture(ABC):
    """Base class for parameter capture strategies."""

    # Capture format identifier for database storage
    CAPTURE_FORMAT: Optional[str] = None

    def capture(self, p: StableDiffusionProcessing) -> Tuple[Dict, List, str]:
        """
        Capture all parameters from a processing object.

        Args:
            p: The StableDiffusionProcessing object to capture from.

        Returns:
            Tuple of (params dict, script_args list, checkpoint string)
        """
        # Determine task type
        is_img2img = hasattr(p, 'init_images') and p.init_images
        task_type = TaskType.IMG2IMG if is_img2img else TaskType.TXT2IMG

        # Capture core parameters (implementation-specific)
        params = self._capture_core_params(p)

        # Capture override settings (shared logic)
        p_override_settings = {}
        if hasattr(p, 'override_settings') and p.override_settings:
            p_override_settings = dict(p.override_settings)

        # Capture UI settings (shared logic)
        ui_settings = self._capture_ui_settings(p_override_settings)
        if ui_settings:
            params["ui_settings"] = ui_settings

        # Save images for img2img (shared logic)
        self._save_images(p, params)

        # Store override settings
        if p_override_settings:
            params["override_settings"] = p_override_settings
            print(f"[TaskScheduler] Captured p.override_settings: {p_override_settings}")

        # Capture extra generation params
        if hasattr(p, 'extra_generation_params') and p.extra_generation_params:
            params["extra_generation_params"] = dict(p.extra_generation_params)
            print(f"[TaskScheduler] Captured extra_generation_params: {list(p.extra_generation_params.keys())}")

        # Get checkpoint
        checkpoint = shared.opts.sd_model_checkpoint or ""

        # Capture script args (shared logic)
        script_args, script_args_labeled = self._capture_script_args(p, task_type)
        if script_args_labeled:
            params["_script_args_labeled"] = script_args_labeled

        return params, script_args, checkpoint

    @abstractmethod
    def _capture_core_params(self, p: StableDiffusionProcessing) -> Dict:
        """Capture core generation parameters. Implementation-specific."""
        pass

    def _capture_ui_settings(self, p_override_settings: Dict) -> Dict:
        """Capture UI-visible settings from shared.opts."""
        try:
            # Essential settings that affect generation
            essential_settings = {
                "sd_vae",                        # VAE
                "CLIP_stop_at_last_layers",      # Clip Skip
                "eta_noise_seed_delta",          # ENSD
                "randn_source",                  # RNG source
                "eta_ancestral",                 # Eta for ancestral samplers
                "eta_ddim",                      # Eta for DDIM
                "s_churn",                       # Sigma churn
                "s_tmin",                        # Sigma tmin
                "s_tmax",                        # Sigma tmax
                "s_noise",                       # Sigma noise
            }

            # Get user's configured quicksettings
            user_quicksettings = set()
            if hasattr(shared.opts, 'quick_setting_list') and shared.opts.quick_setting_list:
                user_quicksettings = set(shared.opts.quick_setting_list)

            # Combine both sets
            settings_to_capture = essential_settings | user_quicksettings

            # Capture values, skip settings already in p.override_settings
            captured_settings = {}
            skipped_settings = []
            for setting_name in settings_to_capture:
                if setting_name in p_override_settings:
                    skipped_settings.append(setting_name)
                    continue
                if hasattr(shared.opts, setting_name):
                    value = getattr(shared.opts, setting_name)
                    captured_settings[setting_name] = value

            # Capture Forge's additional_modules (contains VAE path in Forge)
            # Always capture this, even if empty - so we know to clear VAE during execution
            forge_additional_modules = getattr(shared.opts, "forge_additional_modules", [])
            captured_settings["forge_additional_modules"] = list(forge_additional_modules) if forge_additional_modules else []

            print(f"[TaskScheduler] Captured {len(captured_settings)} UI settings: {list(captured_settings.keys())}")
            if skipped_settings:
                print(f"[TaskScheduler] Skipped {len(skipped_settings)} UI settings (using model overrides): {skipped_settings}")

            return captured_settings
        except Exception as e:
            print(f"[TaskScheduler] Could not capture UI settings: {e}")
            return {}

    def _save_images(self, p: StableDiffusionProcessing, params: Dict) -> None:
        """Save init images and mask for img2img."""
        # Save init images
        if hasattr(p, 'init_images') and p.init_images:
            temp_dir = os.path.join(ext_dir, "temp_images")
            os.makedirs(temp_dir, exist_ok=True)

            init_image_paths = []
            for i, img in enumerate(p.init_images):
                if img is not None:
                    img_filename = f"{uuid.uuid4()}.png"
                    img_path = os.path.join(temp_dir, img_filename)
                    img.save(img_path)
                    init_image_paths.append(img_path)

            params["init_images"] = init_image_paths

        # Save mask if present
        if hasattr(p, 'image_mask') and p.image_mask is not None:
            temp_dir = os.path.join(ext_dir, "temp_images")
            os.makedirs(temp_dir, exist_ok=True)
            mask_filename = f"mask_{uuid.uuid4()}.png"
            mask_path = os.path.join(temp_dir, mask_filename)
            p.image_mask.save(mask_path)
            params["mask_path"] = mask_path

    def _capture_script_args(self, p: StableDiffusionProcessing, task_type: TaskType) -> Tuple[List, Optional[List]]:
        """Capture script arguments for extensions."""
        script_args = []
        script_args_labeled = None

        # Check if ControlNet capture is enabled
        enable_controlnet = getattr(shared.opts, 'task_scheduler_enable_controlnet', False)

        # Identify scripts with complex objects to skip
        scripts_to_skip = set() if enable_controlnet else {"ControlNet", "controlnet"}
        skip_ranges = set()

        if enable_controlnet:
            print("[TaskScheduler] ControlNet capture ENABLED")
        else:
            print("[TaskScheduler] ControlNet capture disabled")

        try:
            from modules import scripts as scripts_module
            script_runner = scripts_module.scripts_txt2img if task_type == TaskType.TXT2IMG else scripts_module.scripts_img2img
            if script_runner:
                for script in script_runner.scripts:
                    script_title = getattr(script, 'title', lambda: '')()
                    if script_title in scripts_to_skip:
                        args_from = getattr(script, 'args_from', None)
                        args_to = getattr(script, 'args_to', None)
                        if args_from is not None and args_to is not None:
                            for idx in range(args_from, args_to):
                                skip_ranges.add(idx)
                            print(f"[TaskScheduler] Skipping {script_title} args [{args_from}:{args_to}]")
        except Exception as e:
            print(f"[TaskScheduler] Error identifying scripts to skip: {e}")

        # Try to get script args mapping for labels
        args_mapping = None
        try:
            from task_scheduler.script_args_mapper import get_cached_mapping
            args_mapping = get_cached_mapping()
            if args_mapping:
                script_args_labeled = []
        except Exception:
            pass

        # Import ControlNet helper if enabled
        controlnet_helper = None
        if enable_controlnet:
            try:
                from task_scheduler.controlnet_helper import serialize_script_arg, is_controlnet_unit
                controlnet_helper = {'serialize': serialize_script_arg, 'is_unit': is_controlnet_unit}
            except ImportError:
                pass

        if hasattr(p, 'script_args') and p.script_args:
            for i, arg in enumerate(p.script_args):
                # Skip complex scripts
                if i in skip_ranges:
                    script_args.append(None)
                    if script_args_labeled is not None:
                        script_args_labeled.append({
                            "index": i,
                            "name": f"arg_{i}",
                            "label": f"[Skipped] Argument {i}",
                            "script": "ControlNet",
                            "type": "skipped",
                            "value": None
                        })
                    continue

                # Serialize the value
                serialized_value = None

                # Try ControlNet serialization first
                if controlnet_helper and controlnet_helper['is_unit'](arg):
                    try:
                        serialized_value = controlnet_helper['serialize'](arg)
                    except Exception:
                        serialized_value = None

                # Fall back to regular serialization
                if serialized_value is None:
                    try:
                        json.dumps(arg)
                        serialized_value = arg
                    except (TypeError, ValueError):
                        if hasattr(arg, 'value'):
                            serialized_value = arg.value
                        elif arg is None:
                            serialized_value = None
                        else:
                            serialized_value = str(arg)

                script_args.append(serialized_value)

                # Build labeled entry
                if script_args_labeled is not None:
                    if args_mapping and i in args_mapping:
                        info = args_mapping[i]
                        script_args_labeled.append({
                            "index": i,
                            "name": info.get("name", f"arg_{i}"),
                            "label": info.get("label", f"Argument {i}"),
                            "script": info.get("script"),
                            "type": info.get("type", "unknown"),
                            "value": serialized_value
                        })
                    else:
                        script_args_labeled.append({
                            "index": i,
                            "name": f"arg_{i}",
                            "label": f"Argument {i}",
                            "script": None,
                            "type": "unknown",
                            "value": serialized_value
                        })

        print(f"[TaskScheduler] Captured {len(script_args)} script_args")
        return script_args, script_args_labeled


class BaseParameterRestore(ABC):
    """Base class for parameter restoration strategies."""

    @abstractmethod
    def create_txt2img(self, params: Dict, override_settings: Dict):
        """
        Create a txt2img processing object from params.

        Args:
            params: The params dict from the task.
            override_settings: Settings to override.

        Returns:
            A configured StableDiffusionProcessingTxt2Img object.
        """
        pass

    @abstractmethod
    def create_img2img(self, params: Dict, override_settings: Dict):
        """
        Create an img2img processing object from params.

        Args:
            params: The params dict from the task.
            override_settings: Settings to override.

        Returns:
            A configured StableDiffusionProcessingImg2Img object.
        """
        pass

    @abstractmethod
    def apply_params(self, p, params: Dict) -> None:
        """
        Apply params from dict to a processing object.

        Args:
            p: The processing object to apply params to.
            params: The params dict from the task.
        """
        pass

    @abstractmethod
    def extract_display_info(self, params: Dict) -> Dict:
        """
        Extract display information from params for API responses.

        Each handler must implement this to extract display fields from
        its specific data format. The returned dict MUST be validated
        against DisplayInfoSchema before returning.

        Args:
            params: The params dict from the task.

        Returns:
            Dict with display-relevant fields, validated against DisplayInfoSchema.

        Raises:
            ValueError: If extracted data doesn't match required schema.
        """
        pass
