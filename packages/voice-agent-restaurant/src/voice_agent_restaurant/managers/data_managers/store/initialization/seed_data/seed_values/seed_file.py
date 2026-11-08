from datetime import date, time
from typing import Final, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantSeedDataInvalidException
from voice_agent_restaurant.managers.models.menu_models import Allergen, DietLabel, MenuCategory
from voice_agent_restaurant.managers.models.restaurant_models import Weekday

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


class SeedFile:
    """Typed reads from one parsed seed file. Every failure names the file and the path of the bad value."""

    FILE_NAME_CONTEXT_KEY: Final[str] = "SeedData.FileName"
    VALUE_PATH_CONTEXT_KEY: Final[str] = "SeedData.ValuePath"

    def __init__(self, file_name: str, root_object: JsonObject) -> None:
        self.file_name: str = file_name
        self.root_object: JsonObject = root_object

    def fail(self, value_path: str, problem: str) -> RestaurantSeedDataInvalidException:
        return RestaurantSeedDataInvalidException(
            message=f"Seed file '{self.file_name}' value '{value_path}' {problem}",
            contextual_data_by_name={self.FILE_NAME_CONTEXT_KEY: self.file_name, self.VALUE_PATH_CONTEXT_KEY: value_path},
        )

    def get_value(self, source_object: JsonObject, key: str, value_path: str) -> JsonValue:
        if key not in source_object:
            raise self.fail(f"{value_path}.{key}", "is missing")
        return source_object[key]

    def get_text(self, source_object: JsonObject, key: str, value_path: str) -> str:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if not isinstance(value, str) or value.strip() == "":
            raise self.fail(f"{value_path}.{key}", f"must be non-empty text but was {value!r}")
        return value

    def get_optional_text(self, source_object: JsonObject, key: str, value_path: str) -> str | None:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if value is None:
            return None
        return self.get_text(source_object, key, value_path)

    def get_whole_number(self, source_object: JsonObject, key: str, value_path: str) -> int:
        value: JsonValue = self.get_value(source_object, key, value_path)
        # bool is a subclass of int in Python, so JSON true and false would otherwise pass as 1 and 0.
        if not isinstance(value, int) or isinstance(value, bool):
            raise self.fail(f"{value_path}.{key}", f"must be a whole number but was {value!r}")
        return value

    def get_positive_number(self, source_object: JsonObject, key: str, value_path: str) -> int:
        value: int = self.get_whole_number(source_object, key, value_path)
        if value < 1:
            raise self.fail(f"{value_path}.{key}", f"must be at least 1 but was {value}")
        return value

    def get_non_negative_number(self, source_object: JsonObject, key: str, value_path: str) -> int:
        value: int = self.get_whole_number(source_object, key, value_path)
        if value < 0:
            raise self.fail(f"{value_path}.{key}", f"must not be negative but was {value}")
        return value

    def get_flag(self, source_object: JsonObject, key: str, value_path: str) -> bool:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if not isinstance(value, bool):
            raise self.fail(f"{value_path}.{key}", f"must be true or false but was {value!r}")
        return value

    def get_object(self, source_object: JsonObject, key: str, value_path: str) -> JsonObject:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if not isinstance(value, dict):
            raise self.fail(f"{value_path}.{key}", "must be an object")
        return value

    def get_objects(self, source_object: JsonObject, key: str, value_path: str) -> list[JsonObject]:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise self.fail(f"{value_path}.{key}", "must be a list of objects")
        return cast(list[JsonObject], value)

    def get_texts(self, source_object: JsonObject, key: str, value_path: str) -> list[str]:
        value: JsonValue = self.get_value(source_object, key, value_path)
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() != "" for item in value):
            raise self.fail(f"{value_path}.{key}", "must be a list of non-empty text values")
        return cast(list[str], value)

    def get_time(self, source_object: JsonObject, key: str, value_path: str) -> time:
        return self.parse_time(self.get_text(source_object, key, value_path), f"{value_path}.{key}")

    def get_optional_time(self, source_object: JsonObject, key: str, value_path: str) -> time | None:
        text_value: str | None = self.get_optional_text(source_object, key, value_path)
        return None if text_value is None else self.parse_time(text_value, f"{value_path}.{key}")

    def get_date(self, source_object: JsonObject, key: str, value_path: str) -> date:
        text_value: str = self.get_text(source_object, key, value_path)
        try:
            return date.fromisoformat(text_value)
        except ValueError as value_error:
            raise self.fail(f"{value_path}.{key}", f"must be a YYYY-MM-DD date but was '{text_value}'") from value_error

    def get_time_zone_name(self, source_object: JsonObject, key: str, value_path: str) -> str:
        time_zone_name: str = self.get_text(source_object, key, value_path)
        try:
            ZoneInfo(time_zone_name)
        except (ZoneInfoNotFoundError, ValueError) as zone_error:
            raise self.fail(f"{value_path}.{key}", f"names an unknown time zone '{time_zone_name}'") from zone_error
        return time_zone_name

    def get_choice[TChoice: (Weekday, MenuCategory, Allergen, DietLabel)](
        self, choice_type: type[TChoice], text_value: str, value_path: str
    ) -> TChoice:
        try:
            return choice_type(text_value)
        except ValueError as value_error:
            valid_choices: str = ", ".join(choice.value for choice in choice_type)
            raise self.fail(value_path, f"'{text_value}' is not one of: {valid_choices}") from value_error

    def parse_time(self, text_value: str, value_path: str) -> time:
        try:
            return time.fromisoformat(text_value)
        except ValueError as value_error:
            raise self.fail(value_path, f"must be an HH:MM time but was '{text_value}'") from value_error
