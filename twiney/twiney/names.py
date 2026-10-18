"""THE NAME DIRECTORY: what the desk calls a stock out loud. "Apple", never "A-A-P-L".

Who wins, in order:
  1. your own names (SETTINGS > Voice > Names: "AAPL=Apple, BRK B=Berkshire")
  2. this directory: the names traders actually say (Nvidia, not NVIDIA Corporation; the S&P for SPY)
  3. the company name IBKR sends for the stock (contract details), tidied: "ADVANCED MICRO DEVICES INC" -> "Advanced Micro Devices"
  4. nothing found: the ticker as it is
"""

import re

DIRECTORY = {
    # index ETFs and the big funds
    "SPY": "the S&P", "SPX": "the S&P", "ES": "S&P futures", "QQQ": "the Nasdaq", "NDX": "the Nasdaq", "NQ": "Nasdaq futures",
    "IWM": "the Russell", "DIA": "the Dow", "VOO": "Vanguard S&P", "VTI": "Vanguard Total Market", "RSP": "equal weight S&P",
    "TQQQ": "triple Q bull", "SQQQ": "triple Q bear", "SPXL": "S&P triple bull", "SPXS": "S&P triple bear", "SPXU": "S&P triple bear",
    "UPRO": "S&P triple bull", "TNA": "Russell triple bull", "TZA": "Russell triple bear", "SOXL": "semis triple bull",
    "SOXS": "semis triple bear", "SMH": "the semis fund", "SOXX": "the semis fund", "XLK": "tech sector", "XLF": "financials",
    "XLE": "energy sector", "XLV": "health care sector", "XLI": "industrials", "XLY": "consumer discretionary", "XLP": "consumer staples",
    "XLU": "utilities", "XLB": "materials", "XLRE": "real estate sector", "XLC": "communication sector", "XBI": "biotech fund",
    "IBB": "biotech fund", "KRE": "regional banks", "KWEB": "China internet", "FXI": "China large cap", "EEM": "emerging markets",
    "EFA": "developed markets", "GLD": "gold", "SLV": "silver", "GDX": "gold miners", "GDXJ": "junior gold miners", "USO": "oil",
    "UNG": "natural gas", "TLT": "long bonds", "IEF": "seven to ten year bonds", "SHY": "short bonds", "HYG": "high yield",
    "LQD": "corporate bonds", "UVXY": "volatility", "VXX": "volatility", "VIX": "the VIX", "ARKK": "Ark Innovation", "IBIT": "the Bitcoin fund",
    "FBTC": "Fidelity Bitcoin", "GBTC": "Grayscale Bitcoin", "ETHA": "the Ether fund", "BITO": "Bitcoin futures fund", "JETS": "airlines fund",
    "TSLL": "Tesla double bull", "NVDL": "Nvidia double bull", "MSTU": "MicroStrategy double bull", "CONL": "Coinbase double bull",
    # mega caps and the names that move
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Google", "GOOG": "Google", "META": "Meta",
    "TSLA": "Tesla", "BRK B": "Berkshire", "BRK.B": "Berkshire", "BRK A": "Berkshire", "BRK.A": "Berkshire", "AVGO": "Broadcom",
    "LLY": "Eli Lilly", "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth", "XOM": "Exxon", "WMT": "Walmart",
    "JNJ": "Johnson and Johnson", "PG": "Procter and Gamble", "HD": "Home Depot", "COST": "Costco", "ORCL": "Oracle", "ABBV": "AbbVie",
    "MRK": "Merck", "CVX": "Chevron", "KO": "Coca-Cola", "PEP": "Pepsi", "BAC": "Bank of America", "NFLX": "Netflix", "CRM": "Salesforce",
    "AMD": "AMD", "ADBE": "Adobe", "TMO": "Thermo Fisher", "WFC": "Wells Fargo", "CSCO": "Cisco", "ACN": "Accenture", "MCD": "McDonald's",
    "ABT": "Abbott", "LIN": "Linde", "DIS": "Disney", "INTU": "Intuit", "TXN": "Texas Instruments", "QCOM": "Qualcomm", "DHR": "Danaher",
    "PM": "Philip Morris", "IBM": "IBM", "VZ": "Verizon", "CAT": "Caterpillar", "AMGN": "Amgen", "GE": "GE Aerospace", "NOW": "ServiceNow",
    "PFE": "Pfizer", "ISRG": "Intuitive Surgical", "UBER": "Uber", "AMAT": "Applied Materials", "GS": "Goldman Sachs", "SPGI": "S&P Global",
    "T": "AT&T", "CMCSA": "Comcast", "NEE": "NextEra", "MS": "Morgan Stanley", "RTX": "RTX", "HON": "Honeywell", "UNP": "Union Pacific",
    "LOW": "Lowe's", "PGR": "Progressive", "BKNG": "Booking", "AXP": "American Express", "COP": "ConocoPhillips", "BLK": "BlackRock",
    "ELV": "Elevance", "SYK": "Stryker", "TJX": "TJ Maxx", "LMT": "Lockheed Martin", "BA": "Boeing", "C": "Citi", "SCHW": "Schwab",
    "VRTX": "Vertex", "MDT": "Medtronic", "BMY": "Bristol Myers", "PLD": "Prologis", "ADP": "ADP", "SBUX": "Starbucks", "MU": "Micron",
    "LRCX": "Lam Research", "ADI": "Analog Devices", "GILD": "Gilead", "DE": "Deere", "MMC": "Marsh McLennan", "CB": "Chubb",
    "KLAC": "KLA", "PANW": "Palo Alto", "ANET": "Arista", "INTC": "Intel", "SO": "Southern Company", "MO": "Altria", "DUK": "Duke Energy",
    "ICE": "ICE", "CME": "CME", "SHW": "Sherwin-Williams", "ZTS": "Zoetis", "CI": "Cigna", "PYPL": "PayPal", "SNPS": "Synopsys",
    "CDNS": "Cadence", "MCK": "McKesson", "CL": "Colgate", "EQIX": "Equinix", "WM": "Waste Management", "TGT": "Target", "NKE": "Nike",
    "MMM": "3M", "FDX": "FedEx", "UPS": "UPS", "CVS": "CVS", "GD": "General Dynamics", "NOC": "Northrop", "ITW": "Illinois Tool Works",
    "EMR": "Emerson", "APD": "Air Products", "MAR": "Marriott", "HLT": "Hilton", "ABNB": "Airbnb", "ORLY": "O'Reilly", "AZO": "AutoZone",
    "CMG": "Chipotle", "MNST": "Monster", "KDP": "Keurig Dr Pepper", "KHC": "Kraft Heinz", "MDLZ": "Mondelez", "HSY": "Hershey",
    "GIS": "General Mills", "K": "Kellanova", "STZ": "Constellation", "TAP": "Molson Coors", "EL": "Estee Lauder", "ULTA": "Ulta",
    "LULU": "Lululemon", "DECK": "Deckers", "ROST": "Ross", "DG": "Dollar General", "DLTR": "Dollar Tree", "BBY": "Best Buy",
    "KR": "Kroger", "WBA": "Walgreens", "F": "Ford", "GM": "GM", "RIVN": "Rivian", "LCID": "Lucid", "NIO": "NIO", "XPEV": "XPeng",
    "LI": "Li Auto", "BYDDY": "BYD", "TM": "Toyota", "HMC": "Honda", "STLA": "Stellantis", "RACE": "Ferrari",
    # tech, software, internet, semis
    "PLTR": "Palantir", "SNOW": "Snowflake", "CRWD": "CrowdStrike", "ZS": "Zscaler", "NET": "Cloudflare", "DDOG": "Datadog",
    "MDB": "MongoDB", "OKTA": "Okta", "FTNT": "Fortinet", "S": "SentinelOne", "TEAM": "Atlassian", "WDAY": "Workday", "HUBS": "HubSpot",
    "SHOP": "Shopify", "SQ": "Block", "XYZ": "Block", "COIN": "Coinbase", "HOOD": "Robinhood", "SOFI": "SoFi", "AFRM": "Affirm",
    "UPST": "Upstart", "MSTR": "MicroStrategy", "MARA": "Marathon Digital", "RIOT": "Riot", "CLSK": "CleanSpark", "HUT": "Hut 8",
    "IREN": "Iris Energy", "CORZ": "Core Scientific", "WULF": "TeraWulf", "CIFR": "Cipher Mining", "BITF": "Bitfarms",
    "SMCI": "Super Micro", "DELL": "Dell", "HPQ": "HP", "HPE": "Hewlett Packard Enterprise", "ARM": "Arm", "ASML": "ASML", "TSM": "Taiwan Semi",
    "MRVL": "Marvell", "ON": "ON Semi", "NXPI": "NXP", "MCHP": "Microchip", "SWKS": "Skyworks", "QRVO": "Qorvo", "WOLF": "Wolfspeed",
    "MPWR": "Monolithic Power", "ENTG": "Entegris", "TER": "Teradyne", "COHR": "Coherent", "LITE": "Lumentum", "CRDO": "Credo",
    "ALAB": "Astera Labs", "AMKR": "Amkor", "GFS": "GlobalFoundries", "UMC": "UMC", "WDC": "Western Digital",
    "STX": "Seagate", "SNDK": "SanDisk", "NTAP": "NetApp", "PSTG": "Pure Storage", "VRT": "Vertiv", "CLS": "Celestica", "ANSS": "Ansys",
    "ADSK": "Autodesk", "ROP": "Roper", "FICO": "FICO", "IT": "Gartner", "CTSH": "Cognizant", "EPAM": "EPAM", "GDDY": "GoDaddy",
    "AKAM": "Akamai", "TWLO": "Twilio", "ZM": "Zoom", "DOCU": "DocuSign", "DBX": "Dropbox", "BOX": "Box", "U": "Unity", "RBLX": "Roblox",
    "EA": "Electronic Arts", "TTWO": "Take-Two", "SPOT": "Spotify", "PINS": "Pinterest", "SNAP": "Snap", "RDDT": "Reddit", "TTD": "Trade Desk",
    "APP": "AppLovin", "ROKU": "Roku", "WBD": "Warner Bros", "PARA": "Paramount", "FOX": "Fox", "FOXA": "Fox", "LYV": "Live Nation",
    "EBAY": "eBay", "ETSY": "Etsy", "W": "Wayfair", "CHWY": "Chewy", "DASH": "DoorDash", "LYFT": "Lyft", "CART": "Instacart",
    "BABA": "Alibaba", "JD": "JD", "PDD": "PDD", "BIDU": "Baidu", "TCEHY": "Tencent", "SE": "Sea", "MELI": "MercadoLibre", "NU": "Nu",
    "CPNG": "Coupang", "GRAB": "Grab", "BILI": "Bilibili", "TME": "Tencent Music", "FUTU": "Futu", "TIGR": "Tiger",
    "AI": "C3 AI", "SOUN": "SoundHound", "BBAI": "BigBear", "PATH": "UiPath", "IONQ": "IonQ", "RGTI": "Rigetti", "QBTS": "D-Wave",
    "QUBT": "Quantum Computing", "ASTS": "AST SpaceMobile", "RKLB": "Rocket Lab", "LUNR": "Intuitive Machines", "ACHR": "Archer",
    "JOBY": "Joby", "OKLO": "Oklo", "SMR": "NuScale", "NNE": "Nano Nuclear", "CEG": "Constellation Energy", "VST": "Vistra",
    "NRG": "NRG", "TLN": "Talen", "CCJ": "Cameco", "LEU": "Centrus", "UEC": "Uranium Energy", "BWXT": "BWX", "GEV": "GE Vernova",
    "FSLR": "First Solar", "ENPH": "Enphase", "SEDG": "SolarEdge", "RUN": "Sunrun", "PLUG": "Plug Power", "BE": "Bloom Energy",
    "CHPT": "ChargePoint", "QS": "QuantumScape", "NVTS": "Navitas", "TEM": "Tempus", "HIMS": "Hims", "CRWV": "CoreWeave", "NBIS": "Nebius",
    "CRCL": "Circle", "OPEN": "Opendoor", "GME": "GameStop", "AMC": "AMC", "BB": "BlackBerry", "DJT": "Trump Media", "CVNA": "Carvana",
    "CELH": "Celsius", "DKNG": "DraftKings", "PENN": "Penn", "MGM": "MGM", "WYNN": "Wynn", "LVS": "Las Vegas Sands", "CZR": "Caesars",
    "RCL": "Royal Caribbean", "CCL": "Carnival", "NCLH": "Norwegian", "DAL": "Delta", "UAL": "United", "AAL": "American Airlines",
    "LUV": "Southwest", "ALK": "Alaska Air", "JBLU": "JetBlue", "EXPE": "Expedia", "TRIP": "Tripadvisor",
    # health care and biotech
    "NVO": "Novo Nordisk", "AZN": "AstraZeneca", "SNY": "Sanofi", "GSK": "GSK", "NVS": "Novartis", "REGN": "Regeneron", "MRNA": "Moderna",
    "BNTX": "BioNTech", "BIIB": "Biogen", "ILMN": "Illumina", "DXCM": "Dexcom", "IDXX": "Idexx", "EW": "Edwards", "BSX": "Boston Scientific",
    "HCA": "HCA", "HUM": "Humana", "CNC": "Centene", "MOH": "Molina", "VKTX": "Viking", "ALNY": "Alnylam", "INSM": "Insmed",
    "SMMT": "Summit", "RXRX": "Recursion", "CRSP": "CRISPR", "NTLA": "Intellia", "BEAM": "Beam", "EXAS": "Exact Sciences", "OSCR": "Oscar",
    # financials
    "BX": "Blackstone", "KKR": "KKR", "APO": "Apollo", "ARES": "Ares", "USB": "US Bancorp", "PNC": "PNC", "TFC": "Truist", "COF": "Capital One",
    "DFS": "Discover", "SYF": "Synchrony", "ALLY": "Ally", "MET": "MetLife", "PRU": "Prudential", "AIG": "AIG", "TRV": "Travelers",
    "ALL": "Allstate", "AFL": "Aflac", "MCO": "Moody's", "MSCI": "MSCI", "NDAQ": "Nasdaq Inc", "CBOE": "Cboe", "IBKR": "Interactive Brokers",
    "RJF": "Raymond James", "LPLA": "LPL", "FI": "Fiserv", "FIS": "FIS", "GPN": "Global Payments", "TOST": "Toast",
    # industrials, energy, materials
    "OXY": "Occidental", "EOG": "EOG", "SLB": "Schlumberger", "HAL": "Halliburton", "BKR": "Baker Hughes", "MPC": "Marathon Petroleum",
    "PSX": "Phillips 66", "VLO": "Valero", "DVN": "Devon", "FANG": "Diamondback", "APA": "APA", "HES": "Hess", "KMI": "Kinder Morgan",
    "WMB": "Williams", "OKE": "Oneok", "ET": "Energy Transfer", "EPD": "Enterprise Products", "LNG": "Cheniere", "FCX": "Freeport",
    "NEM": "Newmont", "GOLD": "Barrick", "AA": "Alcoa", "X": "US Steel", "NUE": "Nucor", "CLF": "Cleveland-Cliffs", "STLD": "Steel Dynamics",
    "MP": "MP Materials", "ALB": "Albemarle", "SQM": "SQM", "LAC": "Lithium Americas", "DOW": "Dow Inc", "DD": "DuPont", "LYB": "LyondellBasell",
    "CTVA": "Corteva", "MOS": "Mosaic", "CF": "CF", "NTR": "Nutrien", "PH": "Parker Hannifin", "ETN": "Eaton", "ROK": "Rockwell",
    "TT": "Trane", "CARR": "Carrier", "JCI": "Johnson Controls", "OTIS": "Otis", "PWR": "Quanta", "URI": "United Rentals",
    "CSX": "CSX", "NSC": "Norfolk Southern", "ODFL": "Old Dominion", "JBHT": "JB Hunt", "CHRW": "CH Robinson", "HII": "Huntington Ingalls",
    "LHX": "L3Harris", "TDG": "TransDigm", "HWM": "Howmet", "AXON": "Axon", "KTOS": "Kratos", "AVAV": "AeroVironment", "SPCE": "Virgin Galactic",
    # real estate, utilities, telecom, consumer
    "AMT": "American Tower", "CCI": "Crown Castle", "O": "Realty Income", "SPG": "Simon Property", "DLR": "Digital Realty", "PSA": "Public Storage",
    "D": "Dominion", "AEP": "American Electric Power", "EXC": "Exelon", "SRE": "Sempra", "PCG": "PG&E", "EIX": "Edison", "TMUS": "T-Mobile",
    "CHTR": "Charter", "YUM": "Yum", "DPZ": "Domino's", "QSR": "Restaurant Brands", "WING": "Wingstop", "CAVA": "Cava", "SHAK": "Shake Shack",
    "DRI": "Darden", "TXRH": "Texas Roadhouse", "BROS": "Dutch Bros", "ELF": "e.l.f.", "CROX": "Crocs", "ONON": "On Running", "BIRK": "Birkenstock",
    "GPS": "Gap", "GAP": "Gap", "ANF": "Abercrombie", "AEO": "American Eagle", "URBN": "Urban Outfitters", "RL": "Ralph Lauren", "TPR": "Tapestry",
    "CPRI": "Capri", "VFC": "VF Corp", "PVH": "PVH", "M": "Macy's", "KSS": "Kohl's", "JWN": "Nordstrom", "WSM": "Williams-Sonoma",
    "RH": "RH", "TSCO": "Tractor Supply", "CASY": "Casey's", "BJ": "BJ's", "SAM": "Boston Beer", "BUD": "AB InBev",
    "DEO": "Diageo", "UL": "Unilever", "SONY": "Sony", "NTDOY": "Nintendo", "SAP": "SAP", "TTE": "TotalEnergies", "SHEL": "Shell", "BP": "BP",
    "RIO": "Rio Tinto", "BHP": "BHP", "VALE": "Vale", "INFY": "Infosys", "HDB": "HDFC Bank", "IBN": "ICICI", "PBR": "Petrobras",
    "ITUB": "Itau", "TD": "TD Bank", "RY": "Royal Bank", "ENB": "Enbridge", "CNQ": "Canadian Natural", "SU": "Suncor", "CP": "Canadian Pacific",
    "CNI": "Canadian National", "MFC": "Manulife", "BMO": "Bank of Montreal", "BNS": "Scotiabank", "TRI": "Thomson Reuters",
}

# what a company name carries that nobody says: "APPLE INC" -> "Apple", "ALPHABET INC-CL A" -> "Alphabet"
_TAIL = re.compile(r"[\s,.&/-]+(SP|SERIES \d+|SHARES|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|LLC|LP|L\.P|NV|N\.V|SA|S\.A|AG|SE|ASA|AB|"
                   r"HOLDINGS?|HLDGS|GROUP|GRP|TRUST|THE|ADR|ADS|SPONSORED|SPON|CLASS [A-Z]|CL [A-Z]|-CL [A-Z]|CL-[A-Z]|COM|NEW|ORD|SHS|"
                   r"REIT|CAPITAL STOCK|COMMON STOCK|COMMON|STOCK|ETF|FUND)\.?$", re.I)
_KEEP_CAPS = {"AI", "AMD", "IBM", "HP", "GE", "UPS", "CVS", "ASML", "SAP", "BP", "NXP", "US", "USA", "AT&T", "AMC", "KLA", "TJX", "ICE", "CME",
              "MSCI", "KKR", "PNC", "AIG", "NRG", "CF", "PVH", "RH", "BJ", "ETF", "S&P", "II", "III", "IV", "UK", "EV", "GSK", "BHP", "TD", "HCA",
              "ADP", "EOG", "APA", "CSX", "LPL", "FIS", "SQM", "XPENG", "NIO", "JD", "PDD", "DJT"}


def tidy(long_name):
    """IBKR's company name as people say it: 'ADVANCED MICRO DEVICES INC' -> 'Advanced Micro Devices'."""
    s = re.sub(r"\s+", " ", str(long_name or "")).strip().strip(",.")
    if not s:
        return ""
    s = re.sub(r"^THE\s+", "", s.split("/")[0].strip(), flags=re.I)     # "PROCTER & GAMBLE CO/THE", "NU HOLDINGS LTD/CAYMAN ISL"
    for _ in range(6):
        t = _TAIL.sub("", re.sub(r"-[A-Z]$", "", s)).strip().strip(",.-&/ ")     # "...INC-A": a share class
        if t == s or not t:
            break
        s = t
    if s.isupper() or s.islower():                      # IBKR sends capitals: give it ordinary capitals
        words = []
        for w in s.split(" "):
            words.append(w if w.upper() in _KEEP_CAPS else "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
        s = " ".join(words)
    s = re.sub(r"\b(\w)'S\b", lambda m: m.group(1) + "'s", s)
    return s.replace(" & ", " and ") if "&" in s and s.upper() not in _KEEP_CAPS else s


def parse_user(text):
    """Your own names from SETTINGS: 'AAPL=Apple, BRK B=Berkshire; SPY = the market' -> {AAPL: Apple, ...}."""
    out = {}
    for part in re.split(r"[,;\n]+", str(text or "")):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = re.sub(r"\s+", " ", k).strip().upper(), v.strip()
        if k and v:
            out[k] = v
    return out


def spoken(symbol, long_name="", user=None):
    """The name the desk says for this ticker."""
    sym = re.sub(r"\s+", " ", str(symbol or "")).strip().upper()
    if not sym:
        return ""
    u = user or {}
    if sym in u:
        return u[sym]
    if sym in DIRECTORY:
        return DIRECTORY[sym]
    t = tidy(long_name)
    return t or sym
