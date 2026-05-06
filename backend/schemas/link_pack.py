from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_FONTS = {"Montserrat", "Inter", "Roboto", "Poppins", "Playfair Display"}


DEFAULT_THEME: dict = {
    "background": {"type": "image", "color": "#c78829"},
    "button": {"bg": "#ffffff", "text": "#1E2330", "shadow": "#eac469", "corner": "pill"},
    "social": {"color": "#ffffff"},
    "typography": {"font": "Montserrat", "color": "#ffffff"},
}


class _ThemeBackground(BaseModel):
    type: Literal["solid", "image"]
    color: str

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("must be a hex color like #aabbcc")
        return v


class _ThemeButton(BaseModel):
    bg: str
    text: str
    shadow: str
    corner: Literal["pill", "rounded", "square"]

    @field_validator("bg", "text", "shadow")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("must be a hex color like #aabbcc")
        return v


class _ThemeSocial(BaseModel):
    color: str

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("must be a hex color like #aabbcc")
        return v


class _ThemeTypography(BaseModel):
    font: str
    color: str

    @field_validator("font")
    @classmethod
    def _font(cls, v: str) -> str:
        if v not in ALLOWED_FONTS:
            raise ValueError(f"font must be one of {sorted(ALLOWED_FONTS)}")
        return v

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("must be a hex color like #aabbcc")
        return v


class ThemeIn(BaseModel):
    background: _ThemeBackground
    button: _ThemeButton
    social: _ThemeSocial
    typography: _ThemeTypography


class ProfileIn(BaseModel):
    profile_name: str = Field(min_length=1, max_length=255)
    profile_bio: str = ""
    is_verified: bool = False


class SocialIn(BaseModel):
    social_phone: Optional[str] = None
    social_email: Optional[str] = None
    social_instagram: Optional[str] = None
    social_facebook: Optional[str] = None
    social_youtube: Optional[str] = None
    social_website: Optional[str] = None
    social_tiktok: Optional[str] = None
    social_x: Optional[str] = None


class ItemIn(BaseModel):
    kind: Literal["classic", "thumbnail", "group", "email_gate"]
    title: str = Field(max_length=255)
    url: Optional[str] = Field(default=None, max_length=2048)
    parent_id: Optional[int] = None
    animation: Literal["none", "pulse", "wobble", "shake", "breathe", "bounce"] = "none"
    is_active: bool = True
    gate_modal_headline: Optional[str] = Field(default=None, max_length=255)
    gate_modal_subtext: Optional[str] = None


class ItemPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    url: Optional[str] = Field(default=None, max_length=2048)
    animation: Optional[Literal["none", "pulse", "wobble", "shake", "breathe", "bounce"]] = None
    is_active: Optional[bool] = None
    gate_modal_headline: Optional[str] = Field(default=None, max_length=255)
    gate_modal_subtext: Optional[str] = None


class ReorderIn(BaseModel):
    parent_id: Optional[int] = None
    ordered_ids: list[int]


class EmailGateSubmit(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not EMAIL_RE.match(v):
            raise ValueError("must be a valid email address")
        return v


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int]
    position: int
    kind: str
    title: str
    url: Optional[str]
    thumbnail_url: Optional[str] = None
    gated_filename: Optional[str] = None
    gate_modal_headline: Optional[str] = None
    gate_modal_subtext: Optional[str] = None
    animation: str
    is_active: bool
    children: list["ItemOut"] = []
