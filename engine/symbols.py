"""NSE symbol directory for search/autocomplete.

Why a bundled list instead of an API call: NSE's own symbol-master endpoint sits
behind the same IP blocking as its quotes, and Yahoo has no good "list all NSE
tickers" call. A static list of the ~150 most-traded NSE names covers what a
personal paper-trading tool realistically needs, works offline, and costs zero
network calls per keystroke. It is NOT the full exchange (~2000 listings) — an
honest limitation; you can still type any symbol manually, search just won't
suggest it.

Each entry: (SYMBOL, Company name, sector-ish tag for display).
"""

from __future__ import annotations

SYMBOLS: list[tuple[str, str, str]] = [
    ("RELIANCE", "Reliance Industries", "Energy/Conglomerate"),
    ("TCS", "Tata Consultancy Services", "IT"),
    ("HDFCBANK", "HDFC Bank", "Banking"),
    ("ICICIBANK", "ICICI Bank", "Banking"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom"),
    ("SBIN", "State Bank of India", "Banking"),
    ("INFY", "Infosys", "IT"),
    ("LICI", "Life Insurance Corporation", "Insurance"),
    ("ITC", "ITC", "FMCG"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    ("LT", "Larsen & Toubro", "Infrastructure"),
    ("BAJFINANCE", "Bajaj Finance", "NBFC"),
    ("HCLTECH", "HCL Technologies", "IT"),
    ("MARUTI", "Maruti Suzuki India", "Auto"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Pharma"),
    ("ADANIENT", "Adani Enterprises", "Conglomerate"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Banking"),
    ("TITAN", "Titan Company", "Consumer"),
    ("ONGC", "Oil & Natural Gas Corporation", "Energy"),
    ("TATAMOTORS", "Tata Motors", "Auto"),
    ("NTPC", "NTPC", "Power"),
    ("AXISBANK", "Axis Bank", "Banking"),
    ("DMART", "Avenue Supermarts (DMart)", "Retail"),
    ("ADANIGREEN", "Adani Green Energy", "Power"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Infrastructure"),
    ("ULTRACEMCO", "UltraTech Cement", "Cement"),
    ("ASIANPAINT", "Asian Paints", "Consumer"),
    ("COALINDIA", "Coal India", "Mining"),
    ("BAJAJFINSV", "Bajaj Finserv", "NBFC"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Auto"),
    ("POWERGRID", "Power Grid Corporation", "Power"),
    ("NESTLEIND", "Nestle India", "FMCG"),
    ("WIPRO", "Wipro", "IT"),
    ("M&M", "Mahindra & Mahindra", "Auto"),
    ("IOC", "Indian Oil Corporation", "Energy"),
    ("JIOFIN", "Jio Financial Services", "NBFC"),
    ("HAL", "Hindustan Aeronautics", "Defence"),
    ("DLF", "DLF", "Realty"),
    ("ADANIPOWER", "Adani Power", "Power"),
    ("JSWSTEEL", "JSW Steel", "Metals"),
    ("TATASTEEL", "Tata Steel", "Metals"),
    ("SIEMENS", "Siemens", "Capital Goods"),
    ("IRFC", "Indian Railway Finance Corp", "NBFC"),
    ("VBL", "Varun Beverages", "FMCG"),
    ("ZOMATO", "Zomato (Eternal)", "Internet"),
    ("PIDILITIND", "Pidilite Industries", "Chemicals"),
    ("GRASIM", "Grasim Industries", "Conglomerate"),
    ("SBILIFE", "SBI Life Insurance", "Insurance"),
    ("HDFCLIFE", "HDFC Life Insurance", "Insurance"),
    ("BEL", "Bharat Electronics", "Defence"),
    ("LTIM", "LTIMindtree", "IT"),
    ("TRENT", "Trent (Westside/Zudio)", "Retail"),
    ("PNB", "Punjab National Bank", "Banking"),
    ("BANKBARODA", "Bank of Baroda", "Banking"),
    ("HINDZINC", "Hindustan Zinc", "Metals"),
    ("HINDALCO", "Hindalco Industries", "Metals"),
    ("TECHM", "Tech Mahindra", "IT"),
    ("INDIGO", "InterGlobe Aviation (IndiGo)", "Aviation"),
    ("GODREJCP", "Godrej Consumer Products", "FMCG"),
    ("AMBUJACEM", "Ambuja Cements", "Cement"),
    ("BRITANNIA", "Britannia Industries", "FMCG"),
    ("CIPLA", "Cipla", "Pharma"),
    ("DRREDDY", "Dr Reddy's Laboratories", "Pharma"),
    ("EICHERMOT", "Eicher Motors (Royal Enfield)", "Auto"),
    ("BPCL", "Bharat Petroleum", "Energy"),
    ("DIVISLAB", "Divi's Laboratories", "Pharma"),
    ("TATAPOWER", "Tata Power", "Power"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare"),
    ("HEROMOTOCO", "Hero MotoCorp", "Auto"),
    ("SHRIRAMFIN", "Shriram Finance", "NBFC"),
    ("CHOLAFIN", "Cholamandalam Investment", "NBFC"),
    ("TVSMOTOR", "TVS Motor Company", "Auto"),
    ("HAVELLS", "Havells India", "Consumer Durables"),
    ("DABUR", "Dabur India", "FMCG"),
    ("MANKIND", "Mankind Pharma", "Pharma"),
    ("VEDL", "Vedanta", "Metals"),
    ("GAIL", "GAIL India", "Energy"),
    ("BOSCHLTD", "Bosch", "Auto Components"),
    ("ZYDUSLIFE", "Zydus Lifesciences", "Pharma"),
    ("LUPIN", "Lupin", "Pharma"),
    ("TORNTPHARM", "Torrent Pharmaceuticals", "Pharma"),
    ("JINDALSTEL", "Jindal Steel & Power", "Metals"),
    ("NAUKRI", "Info Edge (Naukri)", "Internet"),
    ("PFC", "Power Finance Corporation", "NBFC"),
    ("RECLTD", "REC", "NBFC"),
    ("UNIONBANK", "Union Bank of India", "Banking"),
    ("IDBI", "IDBI Bank", "Banking"),
    ("CANBK", "Canara Bank", "Banking"),
    ("INDUSINDBK", "IndusInd Bank", "Banking"),
    ("MOTHERSON", "Samvardhana Motherson", "Auto Components"),
    ("BHEL", "Bharat Heavy Electricals", "Capital Goods"),
    ("SOLARINDS", "Solar Industries", "Chemicals"),
    ("CGPOWER", "CG Power & Industrial", "Capital Goods"),
    ("MAXHEALTH", "Max Healthcare", "Healthcare"),
    ("ABB", "ABB India", "Capital Goods"),
    ("MRF", "MRF", "Tyres"),
    ("PAGEIND", "Page Industries (Jockey)", "Textiles"),
    ("POLYCAB", "Polycab India", "Consumer Durables"),
    ("PERSISTENT", "Persistent Systems", "IT"),
    ("COFORGE", "Coforge", "IT"),
    ("MPHASIS", "Mphasis", "IT"),
    ("OFSS", "Oracle Financial Services", "IT"),
    ("TATAELXSI", "Tata Elxsi", "IT"),
    ("KPITTECH", "KPIT Technologies", "IT"),
    ("PAYTM", "One97 Communications (Paytm)", "Fintech"),
    ("POLICYBZR", "PB Fintech (PolicyBazaar)", "Fintech"),
    ("NYKAA", "FSN E-Commerce (Nykaa)", "Internet"),
    ("DELHIVERY", "Delhivery", "Logistics"),
    ("IRCTC", "IRCTC", "Travel"),
    ("CONCOR", "Container Corporation", "Logistics"),
    ("ASHOKLEY", "Ashok Leyland", "Auto"),
    ("EXIDEIND", "Exide Industries", "Auto Components"),
    ("BATAINDIA", "Bata India", "Consumer"),
    ("JUBLFOOD", "Jubilant FoodWorks (Domino's)", "QSR"),
    ("DEVYANI", "Devyani International (KFC)", "QSR"),
    ("PVRINOX", "PVR INOX", "Entertainment"),
    ("SUNTV", "Sun TV Network", "Media"),
    ("ZEEL", "Zee Entertainment", "Media"),
    ("YESBANK", "Yes Bank", "Banking"),
    ("IDFCFIRSTB", "IDFC First Bank", "Banking"),
    ("FEDERALBNK", "Federal Bank", "Banking"),
    ("AUBANK", "AU Small Finance Bank", "Banking"),
    ("BANDHANBNK", "Bandhan Bank", "Banking"),
    ("MUTHOOTFIN", "Muthoot Finance", "NBFC"),
    ("LICHSGFIN", "LIC Housing Finance", "NBFC"),
    ("SAIL", "Steel Authority of India", "Metals"),
    ("NMDC", "NMDC", "Mining"),
    ("NATIONALUM", "National Aluminium", "Metals"),
    ("BHARATFORG", "Bharat Forge", "Auto Components"),
    ("CUMMINSIND", "Cummins India", "Capital Goods"),
    ("ESCORTS", "Escorts Kubota", "Auto"),
    ("BERGEPAINT", "Berger Paints", "Consumer"),
    ("MARICO", "Marico", "FMCG"),
    ("COLPAL", "Colgate-Palmolive India", "FMCG"),
    ("TATACONSUM", "Tata Consumer Products", "FMCG"),
    ("UBL", "United Breweries", "Beverages"),
    ("MCDOWELL-N", "United Spirits", "Beverages"),
    ("BIOCON", "Biocon", "Pharma"),
    ("AUROPHARMA", "Aurobindo Pharma", "Pharma"),
    ("ALKEM", "Alkem Laboratories", "Pharma"),
    ("GLENMARK", "Glenmark Pharmaceuticals", "Pharma"),
    ("FORTIS", "Fortis Healthcare", "Healthcare"),
    ("LALPATHLAB", "Dr Lal PathLabs", "Healthcare"),
    ("ACC", "ACC", "Cement"),
    ("SHREECEM", "Shree Cement", "Cement"),
    ("DALBHARAT", "Dalmia Bharat", "Cement"),
    ("UPL", "UPL", "Agrochemicals"),
    ("SRF", "SRF", "Chemicals"),
    ("DEEPAKNTR", "Deepak Nitrite", "Chemicals"),
    ("TATACHEM", "Tata Chemicals", "Chemicals"),
    ("ASTRAL", "Astral", "Building Materials"),
    ("SUZLON", "Suzlon Energy", "Power"),
    ("RVNL", "Rail Vikas Nigam", "Infrastructure"),
    ("MAZDOCK", "Mazagon Dock Shipbuilders", "Defence"),
    ("COCHINSHIP", "Cochin Shipyard", "Defence"),
    ("BDL", "Bharat Dynamics", "Defence"),
    ("IREDA", "Indian Renewable Energy Dev", "NBFC"),
    ("HUDCO", "Housing & Urban Development", "NBFC"),
    ("NHPC", "NHPC", "Power"),
    ("SJVN", "SJVN", "Power"),
    # 2024-25 listings
    ("MEESHO", "Meesho", "Internet"),
    ("SWIGGY", "Swiggy", "Internet"),
    ("OLAELEC", "Ola Electric Mobility", "Auto"),
    ("FIRSTCRY", "Brainbees Solutions (FirstCry)", "Internet"),
    ("BAJAJHFL", "Bajaj Housing Finance", "NBFC"),
    ("NTPCGREEN", "NTPC Green Energy", "Power"),
    ("HYUNDAI", "Hyundai Motor India", "Auto"),
    ("VISHALMEGA", "Vishal Mega Mart", "Retail"),
    ("LENSKART", "Lenskart Solutions", "Retail"),
    ("GROWW", "Billionbrains Garage (Groww)", "Fintech"),
    ("PINELABS", "Pine Labs", "Fintech"),
    ("WAAREEENER", "Waaree Energies", "Power"),
    ("PREMIERENE", "Premier Energies", "Power"),
    ("ATHERENERG", "Ather Energy", "Auto"),
]


def search(query: str, limit: int = 10) -> list[dict]:
    """Prefix-first search over symbol and company name.

    Ranking: symbol prefix match first (typing 'REL' should put RELIANCE on
    top), then name prefix, then substring anywhere. Case-insensitive.
    """
    q = (query or "").strip().upper()
    if not q:
        return []
    starts_sym, starts_name, contains = [], [], []
    for sym, name, sector in SYMBOLS:
        entry = {"symbol": sym, "name": name, "sector": sector}
        name_u = name.upper()
        if sym.startswith(q):
            starts_sym.append(entry)
        elif name_u.startswith(q):
            starts_name.append(entry)
        elif q in sym or q in name_u:
            contains.append(entry)
    return (starts_sym + starts_name + contains)[:limit]


def name_of(symbol: str) -> str | None:
    s = (symbol or "").strip().upper()
    for sym, name, _ in SYMBOLS:
        if sym == s:
            return name
    return None
