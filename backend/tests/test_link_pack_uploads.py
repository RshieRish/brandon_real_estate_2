"""Exercise listing photo upload, persistence and publishing with a real database."""

from io import BytesIO

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base, get_db
from middleware.auth import require_admin
from models.link_pack import LinkPack, LinkPackItem
from routers.link_pack import router


def photo_bytes(color="gold", size=(96, 64), format="PNG"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=format)
    return output.getvalue()


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[LinkPack.__table__, LinkPackItem.__table__],
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add(LinkPack(id=1, profile_name="Brandon", profile_bio="", theme={}))
        session.add(LinkPackItem(
            id=28, link_pack_id=1, kind="thumbnail", title="Dracut Expanded Ranch",
            url="https://example.com/listing", position=0, is_active=True,
        ))
        await session.commit()

    async def test_db():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/link-pack")
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[require_admin] = lambda: object()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client
    await engine.dispose()


async def upload(client, data, mime="image/png"):
    return await client.post(
        "/api/v1/link-pack/items/28/thumbnail",
        files={"file": ("listing.png", data, mime)},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("format,mime", [
    ("JPEG", "image/jpeg"), ("PNG", "image/png"),
    ("WEBP", "image/webp"), ("GIF", "image/gif"),
])
async def test_photo_survives_save_reload_publish_and_public_image_read(client, format, mime):
    response = await upload(client, photo_bytes(format=format), mime)
    assert response.status_code == 200

    draft = (await client.get("/api/v1/link-pack/draft")).json()
    path = draft["live"]["items"][0]["thumbnail_url"]
    assert path.startswith("/api/v1/link-pack/images/items/28/thumbnail?v=")
    assert draft["status"]["has_unpublished_changes"] is True
    assert (await client.get("/api/v1/link-pack/draft")).json()["live"]["items"][0]["thumbnail_url"] == path

    assert (await client.post("/api/v1/link-pack/publish")).status_code == 200
    published = (await client.get("/api/v1/link-pack/")).json()
    assert published["items"][0]["thumbnail_url"] == path
    image_response = await client.get(path)
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(image_response.content)) as image:
        assert image.size == (96, 64)


@pytest.mark.asyncio
async def test_high_resolution_photo_above_old_five_mb_limit_is_resized(client):
    # A valid, high-resolution PNG with trailing bytes exceeds the old upload cap.
    data = photo_bytes(size=(2400, 1600)) + b"\0" * (5 * 1024 * 1024)
    response = await upload(client, data)
    assert response.status_code == 200
    draft = (await client.get("/api/v1/link-pack/draft")).json()
    image_response = await client.get(draft["live"]["items"][0]["thumbnail_url"])
    assert len(image_response.content) < 5 * 1024 * 1024
    with Image.open(BytesIO(image_response.content)) as image:
        assert image.size == (1600, 1067)


@pytest.mark.asyncio
async def test_replacement_uses_a_new_image_url_so_cached_photo_cannot_hide_it(client):
    await upload(client, photo_bytes("gold"))
    first = (await client.get("/api/v1/link-pack/draft")).json()["live"]["items"][0]["thumbnail_url"]
    await upload(client, photo_bytes("blue"))
    second = (await client.get("/api/v1/link-pack/draft")).json()["live"]["items"][0]["thumbnail_url"]
    assert first != second


@pytest.mark.asyncio
@pytest.mark.parametrize("data,mime", [
    (b"", "image/png"),
    (b"not a photo", "image/png"),
    (b"unsupported", "image/heic"),
    (b"too large" + b"\0" * (20 * 1024 * 1024), "image/jpeg"),
])
async def test_rejected_photo_preserves_the_previously_saved_photo(client, data, mime):
    await upload(client, photo_bytes())
    path = (await client.get("/api/v1/link-pack/draft")).json()["live"]["items"][0]["thumbnail_url"]
    before = (await client.get(path)).content

    response = await upload(client, data, mime)
    assert response.status_code == 400
    assert response.json()["detail"]
    assert (await client.get(path)).content == before


@pytest.mark.asyncio
async def test_profile_upload_retains_its_existing_five_mb_limit(client):
    response = await client.post(
        "/api/v1/link-pack/profile-photo",
        files={"file": ("profile.png", b"\0" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 400
    assert "5MB" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("format,mime", [("GIF", "image/gif"), ("WEBP", "image/webp")])
async def test_accepted_animated_photo_keeps_its_animation(client, format, mime):
    output = BytesIO()
    Image.new("RGB", (96, 64), "gold").save(
        output, format=format, save_all=True,
        append_images=[Image.new("RGB", (96, 64), "blue")],
        duration=[100, 200], loop=0,
    )
    original = output.getvalue()
    response = await upload(client, original, mime)
    assert response.status_code == 200
    stored = await client.get(response.json()["url"])
    assert stored.headers["content-type"] == mime
    with Image.open(BytesIO(stored.content)) as image:
        assert image.n_frames == 2
        assert image.info["loop"] == 0


@pytest.mark.asyncio
async def test_phone_photo_orientation_is_preserved(client):
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6  # Phone held in portrait; pixels stored sideways.
    Image.new("RGB", (96, 64), "gold").save(output, format="JPEG", exif=exif)
    response = await upload(client, output.getvalue(), "image/jpeg")
    assert response.status_code == 200
    stored = await client.get(response.json()["url"])
    with Image.open(BytesIO(stored.content)) as image:
        assert image.size == (64, 96)


@pytest.mark.asyncio
async def test_transparent_photo_keeps_its_alpha_channel(client):
    output = BytesIO()
    Image.new("RGBA", (96, 64), (255, 215, 0, 128)).save(output, format="PNG")
    response = await upload(client, output.getvalue())
    assert response.status_code == 200
    stored = await client.get(response.json()["url"])
    with Image.open(BytesIO(stored.content)) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((48, 32))[3] == 128


@pytest.mark.asyncio
async def test_oversized_animation_is_rejected_without_erasing_saved_photo(client):
    first = await upload(client, photo_bytes())
    before = await client.get(first.json()["url"])
    output = BytesIO()
    Image.new("RGB", (96, 64), "gold").save(
        output, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (96, 64), "blue")], duration=100, loop=0,
    )
    response = await upload(client, output.getvalue() + b"\0" * (5 * 1024 * 1024), "image/gif")
    assert response.status_code == 400
    assert "Animated images" in response.json()["detail"]
    assert (await client.get(first.json()["url"])).content == before.content
