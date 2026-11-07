from voice_agent_restaurant import RestaurantProfile


class AsserterRestaurantProfile:
    @staticmethod
    def assert_seeded_profile_obligations_hold(
        *,
        expected_restaurant_name: str,
        expected_time_zone: str,
        expected_seating_duration_minutes: int,
        expected_maximum_party_size: int,
        expected_house_note_phrase: str,
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
        if not any(expected_house_note_phrase in house_note for house_note in actual_restaurant_profile.house_notes):
            assertion_failures.append(
                f"House notes: expected one mentioning {expected_house_note_phrase!r}; actual {actual_restaurant_profile.house_notes!r}."
            )
        failure_report: str = "\n".join(assertion_failures)
        assert not failure_report, f"Restaurant profile assertions failed:\n{failure_report}"
