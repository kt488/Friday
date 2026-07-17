"""Friday AI Runtime Harness — Multimodal Support.

Provides image understanding, file analysis, and mixed-media processing
for vision-language models.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class MultimodalProcessor:
    """Processes multimodal inputs: images, documents, and mixed media."""

    SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}
    SUPPORTED_DOC_FORMATS = {"pdf", "txt", "csv", "json", "md"}
    MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB

    def __init__(self, vision_model: Optional[str] = None):
        self._vision_model = vision_model or "meta/llama-3.2-11b-vision-instruct"
        self._history: List[Dict[str, Any]] = []

    def process_image(self, path: str) -> Dict[str, Any]:
        """Process an image file for model consumption."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            return {"success": False, "error": "Image not found"}

        ext = path_obj.suffix.lower().lstrip(".")
        if ext not in self.SUPPORTED_IMAGE_FORMATS:
            return {"success": False, "error": f"Unsupported image format: {ext}"}

        size = path_obj.stat().st_size
        if size > self.MAX_IMAGE_SIZE:
            return {"success": False, "error": f"Image too large ({size / 1024 / 1024:.1f}MB > 20MB)"}

        try:
            with open(path_obj, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            media_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
            result = {
                "success": True,
                "type": "image",
                "format": ext,
                "size_bytes": size,
                "data": b64_data,
                "media_type": media_type,
                "model_ready": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this image."},
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64_data}"}},
                    ],
                },
            }
            self._record("image", path, size)
            return result
        except Exception as e:
            return {"success": False, "error": f"Image processing error: {e}"}

    def process_document(self, path: str) -> Dict[str, Any]:
        """Process a document file."""
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            return {"success": False, "error": "File not found"}

        ext = path_obj.suffix.lower().lstrip(".")
        if ext not in self.SUPPORTED_DOC_FORMATS:
            return {"success": False, "error": f"Unsupported document format: {ext}"}

        try:
            content = path_obj.read_text(encoding="utf-8", errors="replace")
            result = {
                "success": True,
                "type": "document",
                "format": ext,
                "content": content,
                "size_bytes": path_obj.stat().st_size,
                "lines": len(content.split("\n")),
            }
            self._record("document", path, len(content))
            return result
        except Exception as e:
            return {"success": False, "error": f"Document processing error: {e}"}

    def prepare_messages(
        self, text: str, media_paths: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Prepare mixed media messages for LLM consumption."""
        content: List[Dict[str, Any]] = [{"type": "text", "text": text}]

        if media_paths:
            for mp in media_paths:
                path_obj = Path(mp)
                ext = path_obj.suffix.lower().lstrip(".")

                if ext in self.SUPPORTED_IMAGE_FORMATS:
                    result = self.process_image(mp)
                    if result.get("success"):
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{result['media_type']};base64,{result['data']}"},
                        })
                elif ext in self.SUPPORTED_DOC_FORMATS:
                    result = self.process_document(mp)
                    if result.get("success"):
                        content.append({
                            "type": "text",
                            "text": f"\n--- Document: {mp} ---\n{result['content'][:5000]}\n--- End ---\n",
                        })

        return [{"role": "user", "content": content}]

    def get_supported_formats(self) -> Dict[str, List[str]]:
        return {
            "images": list(self.SUPPORTED_IMAGE_FORMATS),
            "documents": list(self.SUPPORTED_DOC_FORMATS),
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._history)
        images = sum(1 for h in self._history if h["type"] == "image")
        docs = sum(1 for h in self._history if h["type"] == "document")
        return {"total_processed": total, "images": images, "documents": docs}

    def _record(self, media_type: str, path: str, size: int) -> None:
        self._history.append({
            "type": media_type,
            "path": path,
            "size": size,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })
