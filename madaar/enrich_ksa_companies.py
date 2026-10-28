import csv, json, re, shutil, sys
from pathlib import Path

BASE = Path(__file__).parent
CSV = BASE / "ksa.csv"
BAK = BASE / "ksa.csv.bak"
DEC = BASE / "output" / "_ksa_decisions.json"

DEF = {
    "jms.sa": ("Jamjoom Medicine Store (JMS)", "Pharmaceutical distributor"),
    "qah.sa": ("Qudurat Alarabia Holding (QAH)", "Investment holding"),
    "noblearchitecture.net": ("Noble Architecture", "Building envelope & fit-out"),
    "advancedtastes.com": ("Advanced Tastes", "Luxury restaurants"),
    "stedltd.com": ("Sted Ltd.", "MEP engineering"),
    "uabco.com": ("United Arab Business Company (UABCO)", "MEP contracting"),
    "tajdhabi.com": ("TAJ Dhabi", "Construction"),
    "source-machinery.com": ("Source Machinery", "Infrastructure & equipment contracting"),
    "redboxsa.com": ("RedBox SA", "Parcel lockers & last-mile logistics"),
    "conpillars.com": ("Construction Pillars Company (CPC)", "Real estate & construction"),
    "mubarrad.sa": ("Mubarrad (Saudi Transport & Investment Co.)", "Logistics & transport"),
    "pt-tgc.com": ("Pioneers Technical (PT)", "Engineering & contracting"),
    "mrk.com.sa": ("M. R. Al Khathlan (MRK)", "Industrial contracting"),
    "fine-mark.com": ("Fine Mark Expo", "Events & exhibitions"),
    "unitedseas.net": ("United Seas Company", "Shipping & logistics"),
    "itruck.com.sa": ("itruck", "Freight platform / transport tech"),
    "alfatech-ksa.com": ("ALFATECH Aluminum Facade Technique Co.", "Aluminum facades & cladding"),
    "alfaisaltransport.com": ("Al Faisal Transport Company", "Transport & logistics"),
    "storagestation.net": ("Storage Station", "E-commerce fulfillment (3PL)"),
    "saudibiga.com": ("Saudi BIGA", "Construction"),
    "rancogroup.com": ("Rabiah & Nassar Group (RANCO)", "Diversified construction group"),
    "risingrayco.com": ("Rising Ray (Shuaa Al-Sa'id)", "Electrical contracting"),
    "parcelat.com": ("Parcelat", "Parcel lockers & last-mile logistics"),
    "alhaitam.com": ("Al-Haitam", "Industrial solutions & trading"),
    "dw.com.sa": ("Development Works Company (DW)", "Investment holding"),
    "intajalamal.com": ("Intaj Logistics Services", "Logistics"),
    "mehwaraleqtisad.com": ("Mehwar Al Eqtisad Co.", "Construction"),
    "gcscontracting.com": ("Gulf Cooperation Symbols Contracting (GCS)", "General contracting (EPC)"),
    "tasawy.com.sa": ("Tasawy Construction Company", "Infrastructure development"),
    "rafia.com.sa": ("Alrafia Contracting", "Contracting / construction"),
    "metalartplus.com": ("Metal ArtWork Saudi Co.", "Metal fabrication & architectural metalwork"),
    "roadco.com.sa": ("Road Logistics (Road Co.)", "Refrigerated / cold-chain transport"),
    "radial.com.sa": ("Radial", "Construction"),
    "rakalspaces.com": ("Rakal Spaces", "Office fit-out"),
    "ethmar-sa.com": ("Ethmar Construction & Building Company", "Construction"),
    "alhussain.co": ("Alhussain Co.", "Cement transport & supply"),
    "saharabuilding.com": ("Sahara Building Contractors (SBC)", "General construction"),
    "sunsetjeddah.com": ("Sunset Jeddah", "Hospitality (hotel)"),
    "ehco.com.sa": ("Economic Houses Contracting (HOMES)", "Construction"),
    "dealcom.sa": ("Dealcom", "Cement & construction materials supplier"),
    "abtltd.com.sa": ("Arabian Bulk Trade (ABT Group)", "Building materials, scaffolding & logistics"),
    "clearvisionarabia.com": ("Clear Vision", "Industrial trading & contracting"),
    "smart-const.com": ("Smart Projects Construction (SPCC)", "Construction"),
    "uneco.com.sa": ("UNECO MEP", "MEP contracting"),
    "almandaryah.com": ("Al-Mandaryah", "Contracting / construction"),
    "rvce.com.sa": ("Riyadh Villas Contracting Company (RVCC)", "Construction"),
    "anwar.io": ("Anwar Mouj AlKhalij Group (AMK)", "Construction & engineering"),
    "anwar.com.sa": ("Anwar Mouj AlKhalij Group (AMK)", "Construction & engineering"),
    "hungrybunny.com.sa": ("Hungry Bunny Company", "Fast food / restaurants"),
    "sedcobc.com": ("SEDCO / Al Mothaberoon", "Building contracting"),
    "safechoice.sa": ("SafeChoice", "Logistics & warehousing"),
    "wefaqnt.com": ("Al Wefaq National Transport", "Freight transport"),
    "meac.eu": ("Middle East Agriculture Company (MEAC)", "Landscaping, agriculture & water mgmt"),
    "meac.net": ("Middle East Agriculture Company (MEAC)", "Landscaping, agriculture & water mgmt"),
    "almarhoon.com.sa": ("Ahmed H. Al-Marhoon & Bros Co.", "Ready-mix concrete"),
    "almad.com": ("ALMAD Contracting", "EPC contracting"),
    "rezapoolscourts.com": ("Pools & Courts (Reza)", "Leisure construction (pools & courts)"),
    "poolscourts.com": ("Pools & Courts (Reza)", "Leisure construction (pools & courts)"),
    "multiworks.eu": ("MultiWorks Co. Ltd", "General contracting (civil)"),
    "mwltd.com.sa": ("MultiWorks Co. Ltd", "General contracting (civil)"),
    "hanmiglobal-mena.com": ("HanmiGlobal MENA", "Construction management"),
    "hanmiglobalsaudi.com": ("HanmiGlobal MENA", "Construction management"),
    "tasami.com.sa": ("Modern Tasami General Contracting Co.", "General contracting"),
    "wyndhamgardendammam.com": ("Wyndham Garden Dammam", "Hospitality (hotel)"),
    "absaco.com": ("Al Barrak Shipping & Cargo (ABSACO)", "Freight forwarding & shipping"),
    "baseel.sa": ("Baseel United Ltd.", "Construction & infrastructure"),
    "baseelunited.com": ("Baseel United Ltd.", "Construction & infrastructure"),
    "saudirockwool.com": ("Saudi Rock Wool Factory (SRW)", "Rock wool insulation manufacturing"),
    "kadlfitout.com": ("KADL", "Fit-out contracting"),
    "alkhozamahotels.com": ("Al Khozama Hotels", "Hospitality (hotel & residences)"),
    "alkhozamakaust.com": ("Al Khozama Hotels", "Hospitality (hotel & residences)"),
    "tbo.sa": ("The Burger Original (TBO)", "Fast food / burgers"),
    "sultan-logistics.com": ("Sultan Logistics", "Logistics"),
}

def norm_domain(v):
    if not v:
        return None
    v = v.strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    v = v.split("/")[0]
    return v or None

def main():
    if not CSV.exists():
        sys.exit("ksa.csv not found")
    if not BAK.exists():
        shutil.copy2(CSV, BAK)
    with open(CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if "Company" in header:
        sys.exit("Company column already present")

    w_idx = header.index("website")
    d_idx = header.index("company_domain")
    i_idx = header.index("Industry")
    c_idx = header.index("website") + 1

    new_header = header[:c_idx] + ["Company"] + header[c_idx:]

    stats = {"done": 0, "blank": 0}
    blanks = []
    for r in rows:
        website = norm_domain(r[w_idx])
        domain = norm_domain(r[d_idx])
        pair = None
        for cand in (website, domain):
            if cand in DEF:
                pair = DEF[cand]
                break
        if pair is None:
            stats["blank"] += 1
            blanks.append((r[w_idx], r[d_idx], r[0]))
            r.insert(c_idx, "")
            continue
        company, industry = pair
        r.insert(c_idx, company)
        r[i_idx + 1] = industry
        stats["done"] += 1

    out_rows = rows

    with open(CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        writer.writerows(out_rows)

    with open(DEC, "w") as f:
        json.dump({k: {"company": v[0], "industry": v[1]} for k, v in DEF.items()}, f, indent=1)

    print("header cols:", len(new_header))
    print("rows:", len(out_rows))
    print(stats)
    if blanks:
        print("UNRESOLVED (blank company/industry):")
        for b in blanks:
            print("  ", b)

if __name__ == "__main__":
    main()