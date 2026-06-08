import json
import os
import time

import pandas as pd
import requests


SERVICE_URL = os.getenv("RECSYS_SERVICE_URL", "http://127.0.0.1:8000")


def wait_service():
    """
    Ждёт, пока сервис станет доступен.
    """
    for _ in range(30):
        try:
            response = requests.get(SERVICE_URL + "/", timeout=2)

            if response.status_code == 200:
                print("Service is ready")
                print(response.json())
                return

        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

    raise RuntimeError("Service is not available")


def post(path, params):
    """
    Выполняет POST-запрос к сервису и печатает результат.
    """
    url = SERVICE_URL + path

    response = requests.post(
        url,
        params=params,
        timeout=30,
    )

    print(f"\nPOST {path}")
    print("params:", params)
    print("status_code:", response.status_code)

    response.raise_for_status()

    data = response.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))

    return data


def assert_recommendations_response(data, k):
    """
    Проверяет базовый формат ответа с рекомендациями.
    """
    assert "recs" in data
    assert isinstance(data["recs"], list)
    assert len(data["recs"]) == k


def main():
    wait_service()

    k = 5

    recommendations = pd.read_parquet(
        "recommendations.parquet",
        columns=["user_id", "track_id", "rank"],
    )

    similar = pd.read_parquet(
        "similar.parquet",
        columns=["track_id_1", "track_id_2", "rank"],
    )

    personal_users = recommendations["user_id"].drop_duplicates().to_list()

    user_without_personal = int(max(personal_users) + 10_000_000)
    user_with_personal_no_online = int(personal_users[0])
    user_with_personal_and_online = int(personal_users[1])

    event_track_id = int(similar["track_id_1"].iloc[0])

    print("\n=== Test 1: user without personal recommendations ===")
    print("Expected: service returns top-popular fallback recommendations")

    result = post(
        "/recommendations",
        {
            "user_id": user_without_personal,
            "k": k,
        },
    )

    assert_recommendations_response(result, k)

    print("\n=== Test 2: user with personal recommendations, without online history ===")
    print("Expected: service returns offline personal recommendations")

    result = post(
        "/recommendations",
        {
            "user_id": user_with_personal_no_online,
            "k": k,
        },
    )

    assert_recommendations_response(result, k)

    print("\n=== Test 3: user with personal recommendations and online history ===")
    print("Expected: service uses recent event and blends online/offline recommendations")

    put_result = post(
        "/put",
        {
            "user_id": user_with_personal_and_online,
            "track_id": event_track_id,
        },
    )

    assert put_result["result"] == "ok"

    history = post(
        "/get",
        {
            "user_id": user_with_personal_and_online,
            "k": 3,
        },
    )

    assert event_track_id in history["events"]

    online_result = post(
        "/recommendations_online",
        {
            "user_id": user_with_personal_and_online,
            "k": k,
        },
    )

    assert_recommendations_response(online_result, k)

    blended_result = post(
        "/recommendations",
        {
            "user_id": user_with_personal_and_online,
            "k": k,
        },
    )

    assert_recommendations_response(blended_result, k)
    assert event_track_id not in blended_result["recs"]

    print("\nAll tests passed")


if __name__ == "__main__":
    main()