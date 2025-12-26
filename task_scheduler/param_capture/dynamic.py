"""
Dynamic parameter capture and restoration that handles all serializable attributes.

This approach is future-proof - any new fields Forge adds will be automatically
captured and restored.
"""
import json
import os
from typing import Dict

from modules import scripts, shared
from modules.processing import (
    StableDiffusionProcessing,
    StableDiffusionProcessingTxt2Img,
    StableDiffusionProcessingImg2Img,
)
from PIL import Image

from .base import BaseParameterCapture, BaseParameterRestore


class DynamicParameterCapture(BaseParameterCapture):
    """
    Dynamic parameter capture that serializes all attributes from the processing object.
    """

    CAPTURE_FORMAT = "dynamic"

    def _capture_core_params(self, p: StableDiffusionProcessing) -> Dict:
        """Dynamically capture all serializable attributes from processing object."""
        params = {}

        for attr_name in dir(p):
            # Skip private/magic attributes
            if attr_name.startswith('_'):
                continue
            try:
                value = getattr(p, attr_name)
                # Skip methods/callables
                if callable(value):
                    continue
                # Try to serialize - if it works, keep it
                json.dumps(value)
                params[attr_name] = value
            except (TypeError, ValueError, AttributeError):
                # Not serializable, skip silently
                pass

        print(f"[TaskScheduler] DynamicCapture: captured {len(params)} parameters")
        return params


class DynamicParameterRestore(BaseParameterRestore):
    """
    Dynamic parameter restoration that applies all params from dict.
    """

    # Keys that are handled separately (not set directly on p)
    SKIP_KEYS = {
        "ui_settings", "override_settings", "extra_generation_params",
        "_script_args_labeled", "init_images", "mask_path",
        # Constructor-only params that shouldn't be set after creation
        "outpath_samples", "outpath_grids",
    }

    def create_txt2img(self, params: Dict, override_settings: Dict) -> StableDiffusionProcessingTxt2Img:
        """Create a txt2img processing object and apply all params dynamically."""
        base_samples = shared.opts.outdir_samples or shared.opts.outdir_txt2img_samples
        base_grids = shared.opts.outdir_grids or shared.opts.outdir_txt2img_grids

        # Create with minimal constructor args
        p = StableDiffusionProcessingTxt2Img(
            outpath_samples=base_samples,
            outpath_grids=base_grids,
            override_settings=override_settings,
        )

        # Apply all params dynamically
        self._apply_all_params(p, params)

        # Set scripts
        p.scripts = scripts.scripts_txt2img

        print("[TaskScheduler] DynamicRestore: created txt2img processing object")
        return p

    def create_img2img(self, params: Dict, override_settings: Dict) -> StableDiffusionProcessingImg2Img:
        """Create an img2img processing object and apply all params dynamically."""
        base_samples = shared.opts.outdir_samples or shared.opts.outdir_img2img_samples
        base_grids = shared.opts.outdir_grids or shared.opts.outdir_img2img_grids

        # Load init images
        init_images = []
        init_image_paths = params.get("init_images", [])
        for img_path in init_image_paths:
            try:
                img = Image.open(img_path)
                init_images.append(img)
            except Exception as e:
                print(f"[TaskScheduler] Failed to load init image: {img_path} - {e}")

        if not init_images:
            raise ValueError("No valid init images found for img2img task")

        # Load mask if present
        mask = None
        mask_path = params.get("mask_path")
        if mask_path:
            try:
                mask = Image.open(mask_path)
            except Exception as e:
                print(f"[TaskScheduler] Failed to load mask: {mask_path} - {e}")

        # Create with minimal constructor args + required img2img params
        p = StableDiffusionProcessingImg2Img(
            outpath_samples=base_samples,
            outpath_grids=base_grids,
            init_images=init_images,
            mask=mask,
            override_settings=override_settings,
        )

        # Apply all params dynamically
        self._apply_all_params(p, params)

        # Set scripts
        p.scripts = scripts.scripts_img2img

        print("[TaskScheduler] DynamicRestore: created img2img processing object")
        return p

    def _apply_all_params(self, p, params: Dict) -> None:
        """Apply all params from dict to processing object."""
        applied = []
        skipped = []
        for key, value in params.items():
            if key in self.SKIP_KEYS or key.startswith("_"):
                continue
            # Skip None values to avoid overwriting defaults with None
            if value is None:
                skipped.append(key)
                continue
            if hasattr(p, key):
                try:
                    setattr(p, key, value)
                    applied.append(key)
                except Exception:
                    pass  # Skip if can't set

        print(f"[TaskScheduler] DynamicRestore: applied {len(applied)} params, skipped {len(skipped)} None values")

    def apply_params(self, p, params: Dict) -> None:
        """Apply params - used if called separately."""
        self._apply_all_params(p, params)

    def extract_display_info(self, params: Dict) -> Dict:
        """
        Extract display information from dynamic format params.

        Dynamic format uses the same attribute names as StableDiffusionProcessing,
        so extraction logic is similar to legacy.

        Returns:
            Dict validated against DisplayInfoSchema.
        """
        from .schema import validate_display_info

        ui_settings = params.get("ui_settings", {})
        override_settings = params.get("override_settings", {})

        # Get VAE filename - priority: forge_additional_modules > override_settings > ui_settings
        vae = ""

        # Check Forge's additional_modules first (contains full VAE path)
        forge_modules = ui_settings.get("forge_additional_modules", [])
        if forge_modules:
            for module_path in forge_modules:
                if module_path and ("vae" in module_path.lower() or "VAE" in module_path):
                    vae = os.path.basename(module_path)
                    break
            if not vae and forge_modules:
                vae = os.path.basename(forge_modules[0])

        # Fall back to override_settings, then ui_settings
        if not vae:
            vae = override_settings.get("sd_vae") or ui_settings.get("sd_vae", "")

        if vae in ("Automatic", "None", ""):
            vae = ""

        # Hires fix info
        enable_hr = params.get("enable_hr", False)
        hr_resize_x = params.get("hr_resize_x", 0)
        hr_resize_y = params.get("hr_resize_y", 0)
        hr_scale = params.get("hr_scale", 2.0)
        width = params.get("width", 512)
        height = params.get("height", 512)

        # Calculate upscaled size
        upscaled_width = 0
        upscaled_height = 0
        if enable_hr:
            if hr_resize_x > 0 and hr_resize_y > 0:
                upscaled_width = hr_resize_x
                upscaled_height = hr_resize_y
            elif hr_scale > 0:
                upscaled_width = int(width * hr_scale)
                upscaled_height = int(height * hr_scale)

        result = {
            "vae": vae,
            "sampler_name": params.get("sampler_name", ""),
            "scheduler": params.get("scheduler", ""),
            "width": width,
            "height": height,
            "enable_hr": enable_hr,
            "upscaled_width": upscaled_width,
            "upscaled_height": upscaled_height,
            "batch_size": params.get("batch_size", 1),
            "n_iter": params.get("n_iter", 1),
        }

        return validate_display_info(result)
