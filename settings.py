"""Fixed demonstrative execution settings, never sourced from an order request."""
TRADE_AMOUNT=100
MAX_OPEN_POSITIONS=3
MAJOR_PAIRS=('EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','USDCHF')
SINGLE_PAIRS=MAJOR_PAIRS+tuple(p+'-OTC' for p in MAJOR_PAIRS)
BASKET_MODES=('MAJORS','MAJORS-OTC')
ALLOWED_MARKETS=SINGLE_PAIRS+BASKET_MODES

def basket_pairs(mode):
 if mode not in BASKET_MODES:raise ValueError('Invalid basket')
 return MAJOR_PAIRS if mode=='MAJORS' else tuple(p+'-OTC' for p in MAJOR_PAIRS)

MIN_SECONDS_TO_EXPIRY=60
