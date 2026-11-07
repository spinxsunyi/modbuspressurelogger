"""Pressure unit conversions; acquisition and database use PSI exclusively."""
PSI_PER_UNIT = {'psi': 1.0, 'bar': 14.5037738007,
                'kPa': 0.145037738007, 'MPa': 145.037738007}

def from_psi(value, unit):
    """Convert raw PSI to requested display unit."""
    return value / PSI_PER_UNIT[unit]

def to_psi(value, unit):
    """Convert a displayed pressure back to raw PSI."""
    return value * PSI_PER_UNIT[unit]
