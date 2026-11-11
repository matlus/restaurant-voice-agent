from collections.abc import Sequence
from typing import Final

from voice_agent_restaurant import RestaurantProfile


class AsserterRestaurantProfile:
    CHECKED_OBLIGATION_COUNT: Final[int] = 6

    @staticmethod
    def assert_seeded_profile_obligations_hold(
        *,
        expected_restaurant_name: str,
        expected_time_zone: str,
        expected_seating_duration_minutes: int,
        expected_maximum_party_size: int,
        expected_allergen_notice: str,
        expected_house_notes: Sequence[str],
        actual_restaurant_profile: RestaurantProfile,
    ) -> None:
        assertion_failures: list[str] = []
        if actual_restaurant_profile.name != expected_restaurant_name:
            assertion_failures.append(f"Name: expected {expected_restaurant_name!r}; actual {actual_restaurant_profile.name!r}.")
        if actual_restaurant_profile.time_zone != expected_time_zone:
            assertion_failures.append(f"Time zone: expected {expected_time_zone!r}; actual {actual_restaurant_profile.time_zone!r}.")
        if actual_restaurant_profile.reservation_policy.seating_duration_minutes != expected_seating_duration_minutes:
            assertion_failures.append(
                f"Seating duration: expected {expected_seating_duration_minutes}; "
                f"actual {actual_restaurant_profile.reservation_policy.seating_duration_minutes}."
            )
        if actual_restaurant_profile.reservation_policy.maximum_party_size != expected_maximum_party_size:
            assertion_failures.append(
                f"Maximum party size: expected {expected_maximum_party_size}; "
                f"actual {actual_restaurant_profile.reservation_policy.maximum_party_size}."
            )
        if actual_restaurant_profile.allergen_notice != expected_allergen_notice:
            assertion_failures.append(
                f"Allergen notice: expected {expected_allergen_notice!r}; actual {actual_restaurant_profile.allergen_notice!r}."
            )
        if actual_restaurant_profile.house_notes != list(expected_house_notes):
            assertion_failures.append(f"House notes: expected {list(expected_house_notes)!r}; actual {actual_restaurant_profile.house_notes!r}.")
        failure_report: str = "\n".join(assertion_failures)
        assert not failure_report, (
            f"The profile of {expected_restaurant_name!r} must hold the seeded values the agent tells a guest: its name, time zone, "
            f"seating duration, largest party bookable by phone, allergen notice and house notes; {len(assertion_failures)} of "
            f"{AsserterRestaurantProfile.CHECKED_OBLIGATION_COUNT} profile obligations unmet:\n{failure_report}"
        )
