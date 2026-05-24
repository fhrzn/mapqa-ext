import json
import os
import time
from typing import Dict, List

import httpx
import polars as pl
from tqdm import tqdm

from src.schema.schema import OSMPOI


def osm_lookup(osm_ids: list[any], osm_type: str = "N") -> List[OSMPOI]:
    url = "https://nominatim.openstreetmap.org/lookup"
    batch = [f"{osm_type}{i}" for i in osm_ids]
    params = {
        "osm_ids": ",".join(batch),
        "format": "json",
        "addressdetails": 1,
        "extratags": 1,
        "namedetails": 1,
    }
    headers = {"User-Agent": "mapqa-ext"}

    res = httpx.get(url, params=params, headers=headers)
    return res.json()


def load_qa(base_path: str) -> List[Dict]:
    # basepath = "../dataset/mapqa/llm/california_full/question-answer"

    entities = []
    for fname in tqdm(os.listdir(base_path), desc="processing files"):
        if fname.endswith(".csv"):
            continue

        with open(os.path.join(base_path, fname), "r") as f:
            data = json.loads(f.read())
            for dd in tqdm(data, desc=f"merging {fname}...", leave=False):
                for k, v in data[dd].items():
                    ent = v
                    ent["name"] = k
                    ent["source"] = fname
                    ent["question_id"] = dd
                    entities.append(ent)

    return entities


def main(args):
    entities = load_qa(args.base_path)
    df_qa = pl.DataFrame(entities)
    osm_ids = df_qa.select("osm_id").unique().to_numpy().reshape(-1).tolist()

    pois = []
    for i in tqdm(range(0, len(osm_ids), args.batch_size), desc="batch lookup"):
        batch = osm_ids[i : i + args.batch_size]
        res = osm_lookup(batch)

        for r in res:
            item = OSMPOI(
                osm_id=r["osm_id"],
                lat=r["lat"],
                lon=r["lon"],
                poi_class=r["class"],
                poi_type=r["type"],
                name=r["name"],
                city=r["address"].get("city")
                or r["address"].get("town")
                or r["address"].get("village"),
                country=r["address"]["country"],
                country_code=r["address"]["country_code"],
                bounding_box=[float(point) for point in r["boundingbox"]],
            )
            pois.append(item)

        time.sleep(1)

    pois_dict = [poi.model_dump() for poi in pois]
    df_pois = pl.DataFrame(pois_dict)

    df_pois.write_json(args.output_path)
    print(f"File output: {args.output_path}")

    # todo: join with df_qa if necessary


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("--base_path")
    parser.add_argument("--batch_size", type=int, default=50)
    parser.add_argument("--output_path")

    args = parser.parse_args()
    main(args)
