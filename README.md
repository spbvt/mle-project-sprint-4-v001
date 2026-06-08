# Проект "Создание рекомендательной системы"

Проект выполнен в рамках 4 спринта "Создание рекомендательной системы".

В проекте реализованы:
* подготовка данных;
* EDA;
* расчёт офлайн-рекомендаций;
* построение похожих треков;
* ранжирование рекомендаций;
* FastAPI-сервис для выдачи рекомендаций;
* тестирование сервиса.

## Подготовка виртуальной машины

### Клонирование репозитория

Склонируйте репозиторий проекта:

```bash
git clone https://github.com/spbvt/mle-project-sprint-4-v001.git
cd mle-project-sprint-4-v001
```

### Создание и активация виртуального окружения

Создайте виртуальное окружение:

```bash
python3 -m venv .venv
```

Активируйте его:

```bash
source .venv/bin/activate
```

Установите зависимости:

```bash
pip install -r requirements.txt
```

## Исходные данные

Для первой части проекта используются три исходных файла:
* `tracks.parquet`;
* `catalog_names.parquet`;
* `interactions.parquet`.

Скачать их можно командами:

```bash
wget https://storage.yandexcloud.net/mle-data/ym/tracks.parquet

wget https://storage.yandexcloud.net/mle-data/ym/catalog_names.parquet

wget https://storage.yandexcloud.net/mle-data/ym/interactions.parquet
```

Эти файлы не добавляются в Git.

## Запуск Jupyter Lab

Для выполнения ноутбука запустите Jupyter Lab:

```bash
jupyter lab --ip=0.0.0.0 --no-browser
```

Код первой части проекта находится в файле:

```text
recommendations.ipynb
```

В ноутбуке выполняются следующие этапы:

1. первичная подготовка данных;
2. EDA;
3. расчёт офлайн-рекомендаций;
4. построение похожих треков;
5. ранжирование рекомендаций;
6. расчёт метрик качества.

## Артефакты рекомендаций

После выполнения ноутбука формируются следующие файлы:

```text
items.parquet
events.parquet
top_popular.parquet
personal_als.parquet
similar.parquet
recommendations.parquet
```

Файлы `items.parquet` и `events.parquet` загружаются в S3-бакет по пути:

```text
recsys/data/
```

Имя бакета: `s3-student-mle-20251214-937fde6138-freetrack`.

Файлы с рекомендациями загружаются в S3 по пути:

```text
recsys/recommendations/
```

Обязательные файлы рекомендаций:

```text
top_popular.parquet
personal_als.parquet
similar.parquet
recommendations.parquet
```

Для запуска сервиса в локальной директории проекта должны находиться файлы:

```text
recommendations.parquet
top_popular.parquet
similar.parquet
```

Скачать файлы из S3 можно в корень проекта командами:

```bash
set -a
source .env
set +a

aws --endpoint-url=https://storage.yandexcloud.net \
    s3 cp s3://$S3_BUCKET/recsys/recommendations/recommendations.parquet recommendations.parquet

aws --endpoint-url=https://storage.yandexcloud.net \
    s3 cp s3://$S3_BUCKET/recsys/recommendations/top_popular.parquet top_popular.parquet

aws --endpoint-url=https://storage.yandexcloud.net \
    s3 cp s3://$S3_BUCKET/recsys/recommendations/similar.parquet similar.parquet
```

Файл с переменными окружения `.env` не добавлялся в Git.

## Сервис рекомендаций

Код сервиса находится в файле:

```text
recommendations_service.py
```

Сервис реализован на FastAPI.

Он использует три источника данных:
* `recommendations.parquet` — офлайн-рекомендации после ранжирования;
* `top_popular.parquet` — fallback-рекомендации для пользователей без персональных рекомендаций;
* `similar.parquet` — похожие треки для онлайн-рекомендаций.

### Запуск сервиса

Активируйте виртуальное окружение:

```bash
source .venv/bin/activate
```

Запустите сервис:

```bash
uvicorn recommendations_service:app --host 0.0.0.0 --port 8000
```

После запуска сервис доступен по адресу:

```text
http://127.0.0.1:8000
```

Проверка доступности:

```bash
curl http://127.0.0.1:8000/
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

### Endpoint-ы сервиса

Сервис поддерживает следующие endpoint-ы:

```text
GET  /
POST /put
POST /get
POST /recommendations_offline
POST /recommendations_online
POST /recommendations
```

Основной endpoint:

```text
POST /recommendations
```

Он принимает параметры:
* `user_id` — идентификатор пользователя;
* `k` — количество рекомендаций.

Пример запроса:

```bash
curl -X POST "http://127.0.0.1:8000/recommendations?user_id=5&k=5"
```

Пример ответа:

```json
{
  "recs": [21846409, 328683, 20111365, 1710811, 26343802]
}
```

## Стратегия смешивания онлайн- и офлайн-рекомендаций

Сервис использует два типа рекомендаций.

### Офлайн-рекомендации

Офлайн-рекомендации заранее рассчитаны в ноутбуке `recommendations.ipynb` и сохранены в файле:

```text
recommendations.parquet
```

Они отражают долгосрочные интересы пользователя.

Если для пользователя нет персональных офлайн-рекомендаций, сервис использует fallback из файла:

```text
top_popular.parquet
```

### Онлайн-рекомендации

Онлайн-рекомендации строятся по последним событиям пользователя.

Событие можно добавить через endpoint:

```text
POST /put
```

Сервис хранит последние события пользователя в памяти. Для последних треков пользователя сервис находит похожие треки в файле:

```text
similar.parquet
```

### Итоговое смешивание

Итоговый список рекомендаций строится чередованием онлайн- и офлайн-рекомендаций:

```text
online_1, offline_1, online_2, offline_2, ...
```

После смешивания сервис:
* удаляет дубликаты;
* исключает треки, которые уже есть в онлайн-истории пользователя;
* при необходимости дополняет список популярными треками.

Если у пользователя нет онлайн-истории, сервис возвращает офлайн-рекомендации.

Если у пользователя нет персональных рекомендаций, сервис возвращает популярные треки.

## Тестирование сервиса

Код тестирования находится в файле:

```text
test_service.py
```

Скрипт проверяет три сценария:
1. пользователь без персональных рекомендаций;
2. пользователь с персональными рекомендациями, но без онлайн-истории;
3. пользователь с персональными рекомендациями и онлайн-историей.

Перед запуском теста сервис должен быть запущен:

```bash
uvicorn recommendations_service:app --host 0.0.0.0 --port 8000
```

В отдельном терминале запустите тест:

```bash
python test_service.py | tee test_service.log
```

Результат тестирования сохраняется в файл:

```text
test_service.log
```

Успешное выполнение подтверждается строкой:

```text
All tests passed
```

## Результаты тестирования

В проект добавлен файл:

```text
test_service.log
```

Он содержит вывод тестового скрипта и подтверждает, что сервис успешно обрабатывает три обязательных сценария.
