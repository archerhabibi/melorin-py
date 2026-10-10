def commission_amount(net_paid: int, percent_bp: int) -> int:
    """percent in basis points (1% = 100) on net paid after discount; floor to integer unit."""
    if net_paid <= 0 or percent_bp <= 0:
        return 0
    return net_paid * percent_bp // 10_000
