# ===== CURRENCY TYPES =====

VALID_CURRENCY_TYPES = ("gold", "silver", "copper")


# ===== CONVERSION RATES (NO AUTO-CONVERSION) =====

# These are reference values for systems like merchants or banks.
# The currency system itself does NOT automatically convert values.

CURRENCY_CONVERSION_RATES = {
    "gold_to_silver": 10,
    "silver_to_copper": 50,
}

# Derived value (for convenience)
GOLD_TO_COPPER = (
    CURRENCY_CONVERSION_RATES["gold_to_silver"]
    * CURRENCY_CONVERSION_RATES["silver_to_copper"]
)