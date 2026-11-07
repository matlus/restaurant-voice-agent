from datetime import datetime


class AgentInstructions:
    """Composes what the speech model is told about its role before the guest says anything."""

    @classmethod
    def compose(cls, restaurant_name: str, restaurant_local_now: datetime) -> str:
        # The model has no clock. Stating the restaurant's own date and time lets it resolve "tonight" or "this Friday".
        local_now_description: str = cls._describe_local_now(restaurant_local_now)
        return "\n".join(
            [
                f"You are the host who answers the phone at {restaurant_name}, a restaurant.",
                f"Right now it is {local_now_description} at the restaurant.",
                f"Greet the caller warmly in one short sentence that names {restaurant_name}, then ask how you can help.",
                "Speak naturally and briefly, the way a friendly host does on a call: one or two sentences at a time.",
                "If the caller interrupts you, stop and listen.",
                "You cannot look up the menu, opening hours or reservations yet. If asked, say so politely",
                "and suggest the caller visit the restaurant's website or call back later.",
                "Never invent dishes, prices, hours, allergen facts or bookings.",
            ]
        )

    @staticmethod
    def _describe_local_now(restaurant_local_now: datetime) -> str:
        # strftime always zero-pads %d and %I, and the unpadded directives differ by platform, so the padding is
        # stripped afterwards: the model should say "November 4 at 3:00 PM", not "November 04 at 03:00 PM".
        return restaurant_local_now.strftime("%A, %B %d, %Y, at %I:%M %p").replace(" 0", " ")
