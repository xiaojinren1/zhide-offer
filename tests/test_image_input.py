"""图片简历输入：格式校验、认证边界和视觉 JSON 调用契约。"""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from main import app
from core.accounts import require_user
from engine.models import Experience, ResumeProfile
from engine.resume_parser import image_data_uri, parse_resume_image, validate_image


def png_bytes(size=(32, 16)):
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", size, color=(240, 240, 240)).save(stream, format="PNG")
    return stream.getvalue()


def gif_bytes():
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (8, 8), color=(240, 240, 240)).save(stream, format="GIF")
    return stream.getvalue()


class ImageInputContract(unittest.TestCase):
    def setUp(self):
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[require_user] = lambda: {"id": "image-user", "username": "image_user"}
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
        self.addCleanup(self.client.close)
        self.profile = ResumeProfile(
            name="图片同学",
            experiences=[Experience(name="图片项目", actions=["整理需求"])],
            raw_text="[图片材料：resume.png]",
            user_confirmed=False,
        )

    def test_image_validation_and_data_uri(self):
        content = png_bytes()
        self.assertEqual(validate_image(content, "resume.png"), ("image/png", 32, 16))
        uri = image_data_uri(content, "resume.png")
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        with self.assertRaisesRegex(ValueError, "无法读取"):
            validate_image(b"not-an-image", "resume.png")
        with self.assertRaisesRegex(ValueError, "JPG、PNG 或 WebP"):
            validate_image(gif_bytes(), "resume.gif")

    def test_parse_image_uses_multimodal_helper_and_keeps_unconfirmed(self):
        with patch(
            "engine.resume_parser.chat_json_multimodal",
            return_value={"name": "图片同学", "experiences": [{"name": "图片项目", "actions": ["整理需求"]}]},
        ) as model:
            profile = parse_resume_image(png_bytes(), "resume.png")
        self.assertEqual(profile.name, "图片同学")
        self.assertFalse(profile.user_confirmed)
        self.assertIn("resume.png", profile.raw_text)
        args = model.call_args.args
        self.assertIn("data:image/png;base64,", args[2])

    def test_parse_image_rejects_empty_model_result(self):
        with patch(
            "engine.resume_parser.chat_json_multimodal",
            return_value={"name": "", "experiences": [{}], "skills": [], "education": []},
        ):
            with self.assertRaisesRegex(ValueError, "图片未识别到可用简历内容"):
                parse_resume_image(png_bytes(), "resume.png")

    def test_parse_image_accepts_content_without_name(self):
        with patch(
            "engine.resume_parser.chat_json_multimodal",
            return_value={"name": "", "experiences": [{"name": "图片项目", "actions": ["整理需求"]}]},
        ):
            profile = parse_resume_image(png_bytes(), "resume.png")
        self.assertEqual(profile.name, "")
        self.assertEqual(profile.experiences[0].name, "图片项目")

    def test_route_returns_error_for_empty_model_result(self):
        with patch("api.resume.is_configured", return_value=True), patch(
            "api.resume.parse_resume_image",
            side_effect=ValueError("图片未识别到可用简历内容，请上传更清晰的图片或更换支持视觉输入的模型"),
        ):
            response = self.client.post("/api/resume/parse-image", files={"file": ("resume.png", png_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ok"], False)
        self.assertIn("图片未识别到可用简历内容", response.json()["error"])
        self.assertNotIn("profile", response.json())

    def test_route_requires_model_and_returns_profile(self):
        with patch("api.resume.is_configured", return_value=False), patch("api.resume.parse_resume_image") as parser:
            response = self.client.post("/api/resume/parse-image", files={"file": ("resume.png", png_bytes(), "image/png")})
        self.assertEqual(response.status_code, 503)
        parser.assert_not_called()

        with patch("api.resume.is_configured", return_value=True), patch("api.resume.parse_resume_image", return_value=self.profile) as parser:
            response = self.client.post("/api/resume/parse-image", files={"file": ("resume.png", png_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(response.json()["profile"]["user_confirmed"])
        parser.assert_called_once()

    def test_route_rejects_invalid_and_oversized_pixels_before_model(self):
        with patch("api.resume.is_configured", return_value=True), patch("api.resume.parse_resume_image") as parser:
            response = self.client.post("/api/resume/parse-image", files={"file": ("resume.gif", gif_bytes(), "image/gif")})
        self.assertEqual(response.status_code, 422)
        parser.assert_not_called()

        with patch("api.resume.is_configured", return_value=True), patch("api.resume.parse_resume_image") as parser:
            response = self.client.post("/api/resume/parse-image", files={"file": ("resume.png", png_bytes((5000, 5000)), "image/png")})
        self.assertEqual(response.status_code, 422)
        parser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
