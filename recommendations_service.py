import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI


logger = logging.getLogger("uvicorn.error")

PERSONAL_RECS_PATH = Path("recommendations.parquet")
DEFAULT_RECS_PATH = Path("top_popular.parquet")
SIMILAR_ITEMS_PATH = Path("similar.parquet")


def remove_duplicates(ids):
    """
    Удаляет повторяющиеся идентификаторы, сохраняя первое вхождение.
    """
    seen = set()
    result = []

    for item_id in ids:
        item_id = int(item_id)

        if item_id not in seen:
            seen.add(item_id)
            result.append(item_id)

    return result


class Recommendations:
    def __init__(self):
        self.personal = None
        self.default = None

    def load(self, personal_path, default_path):
        """
        Загружает персональные и дефолтные рекомендации.
        """
        logger.info("Loading personal recommendations")

        self.personal = pd.read_parquet(
            personal_path,
            columns=["user_id", "track_id", "score", "rank"],
        )

        self.personal = self.personal.sort_values(
            ["user_id", "rank"],
            ascending=[True, True],
        )

        self.personal = self.personal.set_index("user_id")

        logger.info("Loading default recommendations")

        self.default = pd.read_parquet(
            default_path,
            columns=["track_id", "score", "rank"],
        )

        self.default = self.default.sort_values("rank")

        logger.info("Recommendations loaded")

    def get_default(self, k=100):
        """
        Возвращает top-k дефолтных рекомендаций.
        """
        recs = self.default["track_id"].head(k).to_list()
        return [int(item_id) for item_id in recs]

    def get(self, user_id, k=100):
        """
        Возвращает рекомендации для пользователя.
        Если персональных рекомендаций нет, возвращает top-popular fallback.
        """
        try:
            recs = self.personal.loc[int(user_id)]

            if isinstance(recs, pd.Series):
                recs = recs.to_frame().T

            recs = recs.sort_values("rank")["track_id"].head(k).to_list()
            recs = [int(item_id) for item_id in recs]

        except KeyError:
            recs = self.get_default(k)

        return recs


class SimilarItems:
    def __init__(self):
        self.similar = None

    def load(self, path):
        """
        Загружает похожие треки.
        """
        logger.info("Loading similar items")

        self.similar = pd.read_parquet(
            path,
            columns=["track_id_1", "track_id_2", "score", "rank"],
        )

        self.similar = self.similar.sort_values(
            ["track_id_1", "rank"],
            ascending=[True, True],
        )

        self.similar = self.similar.set_index("track_id_1")

        logger.info("Similar items loaded")

    def get(self, track_id, k=100):
        """
        Возвращает похожие треки для track_id.
        """
        try:
            similar = self.similar.loc[int(track_id)]

            if isinstance(similar, pd.Series):
                similar = similar.to_frame().T

            similar = similar.sort_values("rank").head(k)

            result = {
                "track_id_2": [int(item_id) for item_id in similar["track_id_2"].to_list()],
                "score": [float(score) for score in similar["score"].to_list()],
            }

        except KeyError:
            result = {
                "track_id_2": [],
                "score": [],
            }

        return result


class EventStore:
    def __init__(self, max_events_per_user=100):
        self.events = {}
        self.max_events_per_user = max_events_per_user

    def put(self, user_id, track_id):
        """
        Сохраняет событие пользователя.
        Новое событие кладётся в начало списка.
        """
        user_id = int(user_id)
        track_id = int(track_id)

        user_events = self.events.get(user_id, [])
        self.events[user_id] = [track_id] + user_events[: self.max_events_per_user]

    def get(self, user_id, k=10):
        """
        Возвращает последние k событий пользователя.
        """
        user_id = int(user_id)
        user_events = self.events.get(user_id, [])

        return [int(track_id) for track_id in user_events[:k]]


rec_store = Recommendations()
sim_items_store = SimilarItems()
events_store = EventStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting recommendation service")

    rec_store.load(
        personal_path=PERSONAL_RECS_PATH,
        default_path=DEFAULT_RECS_PATH,
    )

    sim_items_store.load(
        path=SIMILAR_ITEMS_PATH,
    )

    logger.info("Recommendation service is ready")

    yield

    logger.info("Stopping recommendation service")


app = FastAPI(title="recommendations", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.post("/put")
async def put(user_id: int, track_id: int):
    """
    Сохраняет событие онлайн-истории пользователя.
    """
    events_store.put(user_id, track_id)
    return {"result": "ok"}


@app.post("/get")
async def get(user_id: int, k: int = 10):
    """
    Возвращает последние k событий пользователя.
    """
    events = events_store.get(user_id, k)
    return {"events": events}


@app.post("/recommendations_offline")
async def recommendations_offline(user_id: int, k: int = 100):
    """
    Возвращает офлайн-рекомендации для пользователя.
    """
    recs = rec_store.get(user_id, k)
    return {"recs": recs}


@app.post("/recommendations_online")
async def recommendations_online(user_id: int, k: int = 100):
    """
    Возвращает онлайн-рекомендации по последним событиям пользователя.
    """
    events = events_store.get(user_id, k=3)

    items = []
    scores = []

    for track_id in events:
        similar = sim_items_store.get(track_id, k=k)

        items += similar["track_id_2"]
        scores += similar["score"]

    combined = list(zip(items, scores))
    combined = sorted(combined, key=lambda x: x[1], reverse=True)

    recs = [track_id for track_id, _ in combined]
    recs = remove_duplicates(recs)

    # Не рекомендуем треки, которые уже есть в онлайн-истории пользователя.
    history = set(events)
    recs = [track_id for track_id in recs if track_id not in history]

    recs = recs[:k]

    return {"recs": recs}


@app.post("/recommendations")
async def recommendations(user_id: int, k: int = 100):
    """
    Возвращает смешанные рекомендации.

    Стратегия:
    - online-рекомендации отражают последние действия пользователя;
    - offline-рекомендации отражают долгосрочные интересы;
    - итоговый список строится чередованием online/offline;
    - треки из онлайн-истории пользователя исключаются.
    """
    offline_response = await recommendations_offline(user_id, k)
    online_response = await recommendations_online(user_id, k)

    offline_recs = offline_response["recs"]
    online_recs = online_response["recs"]

    blended = []

    max_len = max(len(offline_recs), len(online_recs))

    for i in range(max_len):
        if i < len(online_recs):
            blended.append(online_recs[i])

        if i < len(offline_recs):
            blended.append(offline_recs[i])

    blended = remove_duplicates(blended)

    history = set(events_store.get(user_id, k=100))
    blended = [track_id for track_id in blended if track_id not in history]

    # Если после фильтрации рекомендаций стало меньше k,
    # дополняем список дефолтными популярными треками.
    if len(blended) < k:
        blended += rec_store.get_default(k * 2)
        blended = remove_duplicates(blended)
        blended = [track_id for track_id in blended if track_id not in history]

    blended = blended[:k]

    return {"recs": blended}