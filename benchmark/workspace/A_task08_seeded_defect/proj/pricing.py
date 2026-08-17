def calculate_price(quantity, price_per_unit):
    if quantity < 0:
        raise ValueError('Quantity cannot be negative')
    return quantity * price_per_unit