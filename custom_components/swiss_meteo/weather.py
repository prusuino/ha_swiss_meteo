"""The weather entity: current conditions from the station (when one is
configured) and the forecast symbol, with the daily and hourly forecast
lists from the local forecast."""
from __future__ import annotations

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, CONF_POINT_HEIGHT, CONF_POINT_LAT, CONF_POINT_LON, CONF_POINT_NAME, DOMAIN
from .coordinator import EntryData, ForecastCoordinator
from .device import device_info, entry_suffix
from .forecast import daily_forecast, hourly_forecast, value_at
from .localization import t
from .symbols import condition_for, meaning_for


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = entry.runtime_data
    async_add_entities([SwissMeteoWeather(hass, entry, data)])


class SwissMeteoWeather(CoordinatorEntity[ForecastCoordinator], WeatherEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, data: EntryData) -> None:
        super().__init__(data.forecast)
        self._entry = entry
        self._station = data.station
        self._attr_name = None  # the device's main entity carries the device name
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"weather.{DOMAIN}_{entry_suffix(entry)}"
        features = WeatherEntityFeature.FORECAST_DAILY
        if data.forecast.hourly_enabled:
            features |= WeatherEntityFeature.FORECAST_HOURLY
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._station is not None:
            self.async_on_remove(self._station.async_add_listener(self._station_updated))

    @callback
    def _station_updated(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
        # The forecast lists are pushed to subscribed cards.
        self.hass.async_create_task(self.async_update_listeners(None))

    # --- helpers -------------------------------------------------------------

    def _station_value(self, column: str) -> float | None:
        if self._station is None or not self._station.fresh or self._station.data is None:
            return None
        return self._station.data.values.get(column)

    def _hourly_now(self, param: str) -> float | None:
        return value_at(self.coordinator.data.hourly.get(param), dt_util.utcnow())

    def _daytime(self) -> bool | None:
        sun = self.hass.states.get("sun.sun")
        if sun is None or sun.state not in ("above_horizon", "below_horizon"):
            return None
        return sun.state == "above_horizon"

    def _symbol_now(self) -> float | None:
        snap = self.coordinator.data
        symbol = self._hourly_now("jww003i0")
        if symbol is None:
            today = dt_util.now().date()
            for ts, value in snap.daily.get("jp2000d0", []):
                if ts.date() == today:
                    symbol = value
                    break
        return symbol

    # --- state ---------------------------------------------------------------

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None and self.coordinator.data.run is not None

    @property
    def condition(self) -> str | None:
        return condition_for(self._symbol_now(), self._daytime())

    @property
    def native_temperature(self) -> float | None:
        value = self._station_value("tre200s0")
        return value if value is not None else self._hourly_now("tre200h0")

    @property
    def native_dew_point(self) -> float | None:
        return self._station_value("tde200s0")

    @property
    def humidity(self) -> float | None:
        return self._station_value("ure200s0")

    @property
    def native_pressure(self) -> float | None:
        return self._station_value("pp0qnhs0")

    @property
    def native_wind_speed(self) -> float | None:
        value = self._station_value("fu3010z0")
        return value if value is not None else self._hourly_now("fu3010h0")

    @property
    def native_wind_gust_speed(self) -> float | None:
        value = self._station_value("fu3010z1")
        return value if value is not None else self._hourly_now("fu3010h1")

    @property
    def wind_bearing(self) -> float | None:
        value = self._station_value("dkl010z0")
        return value if value is not None else self._hourly_now("dkl010h0")

    @property
    def cloud_coverage(self) -> float | None:
        from .forecast import cloud_coverage

        return cloud_coverage(self.coordinator.data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        symbol = self._symbol_now()
        attrs = {
            "forecast_run": snap.run.isoformat() if snap.run else None,
            "symbol": int(symbol) if symbol is not None else None,
            "symbol_meaning": meaning_for(symbol),
            "precipitation_probability": self._hourly_now("rp0003i0"),
            "global_radiation": self._hourly_now("gre000h0"),
            "zero_degree_level": self._hourly_now("zprfr0hs"),
            # the point itself, for the map card (and Home Assistant's map)
            "point_name": self._entry.data.get(CONF_POINT_NAME),
            "latitude": self._entry.data.get(CONF_POINT_LAT),
            "longitude": self._entry.data.get(CONF_POINT_LON),
            "elevation": self._entry.data.get(CONF_POINT_HEIGHT),
        }
        if self._station is not None and self._station.data is not None:
            attrs["station"] = self._station.station
            attrs["station_time"] = self._station.data.timestamp.isoformat()
            attrs["station_fresh"] = self._station.fresh
        return {k: v for k, v in attrs.items() if v is not None}

    # --- forecasts -----------------------------------------------------------

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return daily_forecast(self.coordinator.data) or None  # type: ignore[return-value]

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        if not self.coordinator.hourly_enabled:
            return None
        return hourly_forecast(self.coordinator.data) or None  # type: ignore[return-value]
