import asyncio
import json
import os
from argparse import ArgumentParser
from typing import List

import httpx
from tqdm.asyncio import tqdm

from src.schema.schema import OSMPOI

POI_CLASSES = ["amenity", "shop", "tourism", "leisure", "office", "historic"]
DEFAULT_HOST = "http://100.69.181.117:4567/"
OVERPASS_ENDPOINT = "api/interpreter"
COUNTRY_ADMIN_MAPPING = {
    "Indonesia": {
        "country_code": "ID",
        "admin_level": 5,
    },
    "Thailand": {
        "country_code": "TH",
        "admin_level": 6,
    },
    "Vietnam": {
        "country_code": "VN",
        "admin_level": 6,
    },
    "Philippines": {
        "country_code": "PH",
        "admin_level": 5,
    },
    "Malaysia": {
        "country_code": "MY",
        "admin_level": 6,
    },
    "Singapore": {
        "country_code": "SG",
        "admin_level": 4,
    },
    "Myanmar": {
        "country_code": "MM",
        "admin_level": 5,
    },
    "Cambodia": {
        "country_code": "KH",
        "admin_level": 6,
    },
    "Laos": {
        "country_code": "LA",
        "admin_level": 5,
    },
    "Timor Leste": {"country_code": "TL", "admin_level": 5},
}


def parse_element(
    elem: dict, country: str, country_code: str, city: str
) -> OSMPOI | None:
    tags = elem.get("tags", {})

    poi_class, poi_type = None, None
    for cls in POI_CLASSES:
        if cls in tags:
            poi_class, poi_type = cls, tags[cls]
            break
    if not poi_class:
        return None

    if elem["type"] == "node":
        lat, lon = elem["lat"], elem["lon"]
        bbox = [lat, lon, lat, lon]
    else:
        b = elem.get("bounds", {})
        bbox = [b.get("minlat"), b.get("minlon"), b.get("maxlat"), b.get("maxlon")]
        lat = (bbox[0] + bbox[2]) / 2 if bbox[0] is not None else None
        lon = (bbox[1] + bbox[3]) / 2 if bbox[1] is not None else None

    return OSMPOI(
        osm_id=elem["id"],
        lat=lat,
        lon=lon,
        poi_class=poi_class,
        poi_type=poi_type,
        name=tags.get("name", ""),
        city=tags.get("addr:city") or tags.get("addr:district") or city,
        country=tags.get("addr:country") or country,
        country_code=tags.get("addr:country_code") or country_code,
        bounding_box=bbox,
    )


def get_pois_qbuilder(
    city: str, poi_classes: List[str], admin_levels: List[int] = [4, 5, 6]
):
    levels = "|".join(str(lvl) for lvl in admin_levels)
    return f"""
        [out:json][timeout:120];
        area["name"~"{city}"]["admin_level"~"{levels}"]->.city;
        (
            {"".join(f'    {elem}["{cls}"](area.city);' + chr(10) for cls in poi_classes for elem in ["node", "way", "relation"])}
        );
        out bb tags;
    """.strip()


async def overpass_request(
    client: httpx.AsyncClient, url: str, query: str, timeout: int = 60
):
    response = await client.post(
        url=url,
        data={"data": query},
        timeout=timeout,
        headers={"User-Agent": "mapqa-ext-sea"},
    )
    response.raise_for_status()
    return response.json()


async def get_cities(
    client: httpx.AsyncClient,
    url: str,
    timeout: int = 60,
    *,
    country_code: str,
    admin_level: str,
):
    query = f"""
        [out:json][timeout:120];
        area["ISO3166-1"="{country_code}"]->.country;
        (
            relation["boundary"="administrative"]
                    ["admin_level"="{admin_level}"]
                    (area.country);
        );
        out center tags;
    """.strip()

    try:
        res = await overpass_request(client, url, query, timeout)
        res = res.get("elements", [])
        cities = [
            {
                "relation_id": r["id"],
                "area_id": r["id"] + 3600000000,
                "name": r["tags"].get("name"),
                "country_code": country_code,
                "lat": r["center"].get("lat"),
                "lon": r["center"].get("lon"),
            }
            for r in res
        ]

        return cities

    except Exception as e:
        print(e)
        return


async def query_poi(
    client: httpx.AsyncClient,
    url: str,
    country: str,
    country_code: str,
    city: str,
    poi_classes: List[str],
):
    query = get_pois_qbuilder(city, poi_classes)
    await asyncio.sleep(5)
    response = await client.post(
        url, data={"data": query}, timeout=60, headers={"User-Agent": "mapqa-ext-sea"}
    )
    try:
        elements = response.json().get("elements", [])
        if not elements:
            print(f"[WARN] POI query on {city} returned an empty result.")
            return elements

        pois = [
            p.model_dump()
            for elem in elements
            if (p := parse_element(elem, country, country_code, city)) is not None
        ]

        return pois
    except Exception as e:
        print(response.content.decode())
        print(e)


async def main(args):
    url = os.path.join(args.url, OVERPASS_ENDPOINT)

    async with httpx.AsyncClient() as client:
        tasks = [
            get_cities(client, url, **v)
            for v in COUNTRY_ADMIN_MAPPING.values()
        ]
        results = await tqdm.gather(*tasks)
    # merge result
    cities = [it for items in results for it in items]
    with open(os.path.join(args.output_dir, "countries.json"), "w") as f:
        f.write(json.dumps(cities, indent=4, ensure_ascii=False))

    # async with httpx.AsyncClient() as client:
    #     tasks = [
    #         query_poi(client, url, args.country, country_code, city, args.poi_classes)
    #         for city in cities
    #     ]

    #     results = await tqdm.gather(*tasks)

    # all_pois = [item for sublist in results for item in sublist]
    # with open(args.output_path, "w") as f:
    #     f.write(json.dumps(all_pois, indent=4))

    # print(f"Successfully write output to: {args.output_path}")


if __name__ == "__main__":
    parser = ArgumentParser()
    # parser.add_argument(
    #     "--country", help="Country name that POIs want to collect", required=True
    # )
    parser.add_argument(
        "--poi-classes",
        nargs="+",
        type=str,
        default=POI_CLASSES,
        help="A list of POI classes",
    )
    parser.add_argument(
        "--output-dir", help="Output directory of generated files", required=True
    )
    parser.add_argument("--url", help="Overpass API URL", default=DEFAULT_HOST)
    args = parser.parse_args()
    asyncio.run(main(args))
