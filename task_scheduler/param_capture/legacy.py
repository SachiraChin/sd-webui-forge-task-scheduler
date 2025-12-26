"""
Legacy parameter capture and restoration using hardcoded field names.

This is the original, stable approach that explicitly captures/restores known fields.
Use this for maximum compatibility with existing tasks.
"""
import os
from typing import Dict, Any

from modules import scripts, shared
from modules.processing import (
    StableDiffusionProcessing,
    StableDiffusionProcessingTxt2Img,
    StableDiffusionProcessingImg2Img,
)
from PIL import Image

from .base import BaseParameterCapture, BaseParameterRestore


class LegacyParameterCapture(BaseParameterCapture):
    """
    Legacy parameter capture using hardcoded field names.
    """

    CAPTURE_FORMAT = None  # Legacy format has no flag (backwards compatible)

    def _capture_core_params(self, p: StableDiffusionProcessing) -> Dict:
        """Capture core parameters using hardcoded field names."""
        params = {
            "prompt": p.prompt,
            "negative_prompt": p.negative_prompt,
            "styles": getattr(p, 'styles', []),
            "seed": p.seed,
            "subseed": p.subseed,
            "subseed_strength": p.subseed_strength,
            "seed_resize_from_h": p.seed_resize_from_h,
            "seed_resize_from_w": p.seed_resize_from_w,
            "sampler_name": p.sampler_name,
            "scheduler": getattr(p, 'scheduler', None),
            "batch_size": p.batch_size,
            "n_iter": p.n_iter,
            "steps": p.steps,
            "cfg_scale": p.cfg_scale,
            "distilled_cfg_scale": getattr(p, 'distilled_cfg_scale', None),
            "width": p.width,
            "height": p.height,
            "restore_faces": p.restore_faces,
            "tiling": p.tiling,
            "do_not_save_samples": p.do_not_save_samples,
            "do_not_save_grid": p.do_not_save_grid,
        }

        # Hires fix params (if enabled)
        if getattr(p, 'enable_hr', False):
            params["enable_hr"] = True
            params["denoising_strength"] = getattr(p, 'denoising_strength', 0.7)
            params["hr_scale"] = getattr(p, 'hr_scale', 2.0)
            params["hr_upscaler"] = getattr(p, 'hr_upscaler', 'Latent')
            params["hr_second_pass_steps"] = getattr(p, 'hr_second_pass_steps', 0)
            params["hr_resize_x"] = getattr(p, 'hr_resize_x', 0)
            params["hr_resize_y"] = getattr(p, 'hr_resize_y', 0)
            params["hr_checkpoint_name"] = getattr(p, 'hr_checkpoint_name', None)
            params["hr_sampler_name"] = getattr(p, 'hr_sampler_name', None)
            params["hr_scheduler"] = getattr(p, 'hr_scheduler', None)
            params["hr_prompt"] = getattr(p, 'hr_prompt', '')
            params["hr_negative_prompt"] = getattr(p, 'hr_negative_prompt', '')
            params["hr_additional_modules"] = getattr(p, 'hr_additional_modules', None)
            params["hr_cfg"] = getattr(p, 'hr_cfg', None)
            params["hr_distilled_cfg"] = getattr(p, 'hr_distilled_cfg', None)

        # Img2img specific params
        if hasattr(p, 'init_images') and p.init_images:
            params["denoising_strength"] = getattr(p, 'denoising_strength', 0.75)
            params["resize_mode"] = getattr(p, 'resize_mode', 0)
            params["image_cfg_scale"] = getattr(p, 'image_cfg_scale', None)
            params["mask_blur"] = getattr(p, 'mask_blur', 4)
            params["inpainting_fill"] = getattr(p, 'inpainting_fill', 0)
            params["inpaint_full_res"] = getattr(p, 'inpaint_full_res', True)
            params["inpaint_full_res_padding"] = getattr(p, 'inpaint_full_res_padding', 0)
            params["inpainting_mask_invert"] = getattr(p, 'inpainting_mask_invert', 0)
            params["initial_noise_multiplier"] = getattr(p, 'initial_noise_multiplier', None)

        print(f"[TaskScheduler] LegacyCapture: captured {len(params)} parameters")
        return params


class LegacyParameterRestore(BaseParameterRestore):
    """
    Legacy parameter restoration using hardcoded field setters.
    """

    def create_txt2img(self, params: Dict, override_settings: Dict) -> StableDiffusionProcessingTxt2Img:
        """Create a txt2img processing object with hardcoded fields."""
        base_samples = shared.opts.outdir_samples or shared.opts.outdir_txt2img_samples
        base_grids = shared.opts.outdir_grids or shared.opts.outdir_txt2img_grids

        # Get hr_cfg values - use defaults if not set (1.0 means "use main cfg")
        hr_cfg_value = params.get("hr_cfg")
        hr_distilled_cfg_value = params.get("hr_distilled_cfg")

        # Build constructor kwargs
        constructor_kwargs = {
            "outpath_samples": base_samples,
            "outpath_grids": base_grids,
            "prompt": params.get("prompt", ""),
            "negative_prompt": params.get("negative_prompt", ""),
            "styles": params.get("prompt_styles", []),
            "batch_size": params.get("batch_size", 1),
            "n_iter": params.get("n_iter", 1),
            "cfg_scale": params.get("cfg_scale", 7.0),
            "distilled_cfg_scale": params.get("distilled_cfg_scale", 3.5),
            "width": params.get("width", 512),
            "height": params.get("height", 512),
            "enable_hr": params.get("enable_hr", False),
            "denoising_strength": params.get("denoising_strength", 0.7),
            "hr_scale": params.get("hr_scale", 2.0),
            "hr_upscaler": params.get("hr_upscaler", "Latent"),
            "hr_second_pass_steps": params.get("hr_second_pass_steps", 0),
            "hr_resize_x": params.get("hr_resize_x", 0),
            "hr_resize_y": params.get("hr_resize_y", 0),
            "hr_checkpoint_name": params.get("hr_checkpoint_name"),
            "hr_additional_modules": params.get("hr_additional_modules", []),
            "hr_sampler_name": params.get("hr_sampler_name"),
            "hr_scheduler": params.get("hr_scheduler"),
            "hr_prompt": params.get("hr_prompt", ""),
            "hr_negative_prompt": params.get("hr_negative_prompt", ""),
            "override_settings": override_settings,
        }

        # Add hr_cfg params to constructor if they have values
        if hr_cfg_value is not None:
            constructor_kwargs["hr_cfg"] = hr_cfg_value
            print(f"[TaskScheduler] Setting hr_cfg in constructor: {hr_cfg_value}")
        if hr_distilled_cfg_value is not None:
            constructor_kwargs["hr_distilled_cfg"] = hr_distilled_cfg_value
            print(f"[TaskScheduler] Setting hr_distilled_cfg in constructor: {hr_distilled_cfg_value}")

        p = StableDiffusionProcessingTxt2Img(**constructor_kwargs)

        # Set additional params
        if "sampler_name" in params:
            p.sampler_name = params["sampler_name"]
        if "scheduler" in params:
            p.scheduler = params["scheduler"]
        if "steps" in params:
            p.steps = params["steps"]
        if "seed" in params:
            p.seed = params["seed"]
        if "subseed" in params:
            p.subseed = params["subseed"]
        if "subseed_strength" in params:
            p.subseed_strength = params["subseed_strength"]

        # Set scripts
        p.scripts = scripts.scripts_txt2img

        print("[TaskScheduler] LegacyRestore: created txt2img processing object")
        return p

    def create_img2img(self, params: Dict, override_settings: Dict) -> StableDiffusionProcessingImg2Img:
        """Create an img2img processing object with hardcoded fields."""
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

        p = StableDiffusionProcessingImg2Img(
            outpath_samples=base_samples,
            outpath_grids=base_grids,
            prompt=params.get("prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            styles=params.get("prompt_styles", []),
            batch_size=params.get("batch_size", 1),
            n_iter=params.get("n_iter", 1),
            cfg_scale=params.get("cfg_scale", 7.0),
            distilled_cfg_scale=params.get("distilled_cfg_scale", 3.5),
            width=params.get("width", 512),
            height=params.get("height", 512),
            init_images=init_images,
            mask=mask,
            mask_blur=params.get("mask_blur", 4),
            inpainting_fill=params.get("inpainting_fill", 0),
            resize_mode=params.get("resize_mode", 0),
            denoising_strength=params.get("denoising_strength", 0.75),
            image_cfg_scale=params.get("image_cfg_scale", 1.5),
            inpaint_full_res=params.get("inpaint_full_res", False),
            inpaint_full_res_padding=params.get("inpaint_full_res_padding", 32),
            inpainting_mask_invert=params.get("inpainting_mask_invert", 0),
            override_settings=override_settings,
        )

        # Set additional params
        if "sampler_name" in params:
            p.sampler_name = params["sampler_name"]
        if "scheduler" in params:
            p.scheduler = params["scheduler"]
        if "steps" in params:
            p.steps = params["steps"]
        if "seed" in params:
            p.seed = params["seed"]
        if "subseed" in params:
            p.subseed = params["subseed"]
        if "subseed_strength" in params:
            p.subseed_strength = params["subseed_strength"]

        # Set scripts
        p.scripts = scripts.scripts_img2img

        print("[TaskScheduler] LegacyRestore: created img2img processing object")
        return p

    def apply_params(self, p, params: Dict) -> None:
        """Legacy doesn't need this - params applied in create methods."""
        pass

    def extract_display_info(self, params: Dict) -> Dict:
        """
        Extract display information from legacy format params.

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
