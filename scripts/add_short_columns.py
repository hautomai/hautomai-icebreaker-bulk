import csv, shutil, sys, re
from pathlib import Path

BASE = Path(__file__).parent
CSV = BASE / "ksa.csv"
BAK = BASE / "ksa.csv.bak2"

SHORT_COMPANY = {
    "Jamjoom Medicine Store (JMS)": "JMS",
    "Qudurat Alarabia Holding (QAH)": "QAH",
    "Noble Architecture": "Noble Arch.",
    "Advanced Tastes": "Advanced Tastes",
    "Sted Ltd.": "Sted",
    "United Arab Business Company (UABCO)": "UABCO",
    "TAJ Dhabi": "TAJ Dhabi",
    "Source Machinery": "Source Mach.",
    "RedBox SA": "RedBox",
    "Construction Pillars Company (CPC)": "CPC",
    "Mubarrad (Saudi Transport & Investment Co.)": "Mubarrad",
    "Pioneers Technical (PT)": "PT",
    "M. R. Al Khathlan (MRK)": "MRK",
    "Fine Mark Expo": "Fine Mark",
    "United Seas Company": "United Seas",
    "itruck": "itruck",
    "ALFATECH Aluminum Facade Technique Co.": "ALFATECH",
    "Al Faisal Transport Company": "Al Faisal Transport",
    "Storage Station": "Storage Station",
    "Saudi BIGA": "BIGA",
    "Rabiah & Nassar Group (RANCO)": "RANCO",
    "Rising Ray (Shuaa Al-Sa'id)": "Rising Ray",
    "Parcelat": "Parcelat",
    "Al-Haitam": "Al-Haitam",
    "Development Works Company (DW)": "DW",
    "Intaj Logistics Services": "Intaj",
    "Mehwar Al Eqtisad Co.": "Mehwar Al Eqtisad",
    "Gulf Cooperation Symbols Contracting (GCS)": "GCS",
    "Tasawy Construction Company": "Tasawy",
    "Alrafia Contracting": "Alrafia",
    "Metal ArtWork Saudi Co.": "Metal ArtWork",
    "Road Logistics (Road Co.)": "Road Logistics",
    "Radial": "Radial",
    "Rakal Spaces": "Rakal",
    "Ethmar Construction & Building Company": "Ethmar",
    "Alhussain Co.": "Alhussain",
    "Sahara Building Contractors (SBC)": "SBC",
    "Sunset Jeddah": "Sunset Jeddah",
    "Economic Houses Contracting (HOMES)": "HOMES",
    "Dealcom": "Dealcom",
    "Arabian Bulk Trade (ABT Group)": "ABT",
    "Clear Vision": "Clear Vision",
    "Smart Projects Construction (SPCC)": "SPCC",
    "UNECO MEP": "UNECO",
    "Al-Mandaryah": "Al-Mandaryah",
    "Riyadh Villas Contracting Company (RVCC)": "RVCC",
    "Anwar Mouj AlKhalij Group (AMK)": "AMK",
    "Hungry Bunny Company": "Hungry Bunny",
    "SEDCO / Al Mothaberoon": "SEDCO",
    "SafeChoice": "SafeChoice",
    "Al Wefaq National Transport": "Al Wefaq",
    "Middle East Agriculture Company (MEAC)": "MEAC",
    "Ahmed H. Al-Marhoon & Bros Co.": "Al-Marhoon",
    "ALMAD Contracting": "ALMAD",
    "Pools & Courts (Reza)": "Reza P&C",
    "MultiWorks Co. Ltd": "MultiWorks",
    "HanmiGlobal MENA": "HanmiGlobal",
    "Modern Tasami General Contracting Co.": "Tasami",
    "Wyndham Garden Dammam": "Wyndham Dammam",
    "Al Barrak Shipping & Cargo (ABSACO)": "ABSACO",
    "Baseel United Ltd.": "Baseel United",
    "Saudi Rock Wool Factory (SRW)": "SRW",
    "KADL": "KADL",
    "Al Khozama Hotels": "Al Khozama",
    "The Burger Original (TBO)": "TBO",
    "Sultan Logistics": "Sultan Logistics",
}

ACRONYMS = [("MEP", "MEP"), ("EPC", "EPC"), ("3PL", "3PL")]

def short_industry(value):
    if not value:
        return ""
    v = value.strip()
    for acro in ("MEP", "EPC", "3PL"):
        if re.search(r"\b" + re.escape(acro) + r"\b", v):
            return acro
    return v

def main():
    if not CSV.exists():
        sys.exit("ksa.csv not found")
    if not BAK.exists():
        shutil.copy2(CSV, BAK)
    with open(CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if "shorten company" in header or "shorten industry" in header:
        sys.exit("shorten columns already present")

    c_idx = header.index("Company")
    i_idx = header.index("Industry")

    new_header = header[: c_idx + 1] + ["shorten company"] + header[c_idx + 1 : i_idx + 1] + ["shorten industry"] + header[i_idx + 1 :]

    missing = []
    out = []
    for r in rows:
        company = r[c_idx]
        industry = r[i_idx] if len(r) > i_idx else ""
        sc = SHORT_COMPANY.get(company, "")
        si = short_industry(industry)
        if company and not sc:
            missing.append(company)
        out.append(r[: c_idx + 1] + [sc] + r[c_idx + 1 : i_idx + 1] + [si] + r[i_idx + 1 :])

    with open(CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        writer.writerows(out)

    print("cols:", len(new_header), "| rows:", len(out))
    print("companies w/o short:", missing)
    print("shorten company empties:", sum(1 for r in out if not r[c_idx + 1]))
    print("shorten industry empties:", sum(1 for r in out if not r[i_idx + 2]))
    print("header:", new_header[36:])

if __name__ == "__main__":
    main()