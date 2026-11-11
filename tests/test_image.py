"""The radar still as an image entity."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.image import RadarImage
from custom_components.swiss_meteo.radar import RadarCoordinator

from .conftest import make_entry
from .feeds import EVERYTHING, entity, entity_object, feeds, setup_everything
from .test_radar import PNG_SIGNATURE, T

IMAGE = entity("image", "radar")


async def test_newest_frame_as_a_picture(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    state = hass.states.get(IMAGE)
    assert state.state == T.isoformat()
    assert state.attributes["radar_time"] == T.isoformat()
    assert state.attributes["km_per_pixel"] == 1
    assert state.attributes["rain_rate"] == 1.5
    assert len(state.attributes["origin_lv95_km"]) == 2

    image = entity_object(hass, IMAGE)
    assert image.content_type == "image/png"
    assert (await image.async_image()).startswith(PNG_SIGNATURE)

    # the next read keeps the time of the frame
    with feeds():
        await entry.runtime_data.radar.async_refresh()
        await hass.async_block_till_done()
    assert image.image_last_updated == T
    assert hass.states.get(IMAGE).state == T.isoformat()


async def test_no_radar_no_image(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, radar=False)
    assert hass.states.get(IMAGE) is None


async def test_nothing_read_yet(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, EVERYTHING)
    image = RadarImage(hass, entry, RadarCoordinator(hass, entry))
    image.hass = hass
    assert image.image_last_updated is None
    assert image.extra_state_attributes == {}
    assert image.available is False
    assert await image.async_image() is None
