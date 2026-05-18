# AGENTS.md — план разработки RESQML Sleeve Property Extractor

## 1. Назначение проекта

Нужно разработать Python-приложение с графической оболочкой **PySide6** для извлечения свойств из RESQML-модели Petrel по координатам муфт ГРП.

Исходные данные:

- RESQML-модель Petrel:
  - `.epc` — структура, метаданные, связи объектов;
  - `.h5` — массивы геометрии и свойств, может быть очень большим, например 17 ГБ.
- Таблица муфт ГРП:
  - минимум: `Sleeve_ID`, `X`, `Y`;
  - желательно: `Well`, `Stage`, `MD`, `TVD`, `Comment`.
- Нужно провести вертикаль через каждую точку `X/Y` муфты и вытащить значения выбранных grid properties по всем пересечённым ячейкам модели.

Итоговая таблица должна иметь вид:

```text
Sleeve_ID | Well | Stage | X | Y | I | J | K | Zone | TVD_top | TVD_base | TVD_center | IsActive | PORO | PERM | NTG | FACIES | ...
```

---

## 2. Критически важные ограничения

### 2.1. Нельзя загружать весь `.h5` в память

Файл `.h5` может быть десятки гигабайт. Запрещено делать такие операции без явного тестового режима:

```python
full_array = dataset[:]
all_properties = load_everything()
all_geometry = load_full_geometry_without_need()
```

Нужно использовать ленивое чтение, батчи и чтение только выбранных данных.

### 2.2. Долгие операции только в worker thread

GUI не должен зависать.

Все долгие операции выполнять через `QThread` / worker objects:

- открытие RESQML;
- чтение метаданных;
- загрузка таблицы муфт;
- расчёт пересечений;
- извлечение свойств;
- экспорт результата.

Должны быть:

- progress bar;
- log panel;
- кнопка `Cancel`;
- аккуратная остановка расчёта по запросу пользователя.

### 2.3. Сначала MVP, потом строгая геометрия

Не начинать с идеального алгоритма для faulted/corner-point grid.

Сначала реализовать рабочий MVP:

```text
X/Y муфты → найти ближайшую или содержащую I/J колонку → пройти все K → вытащить свойства.
```

После этого добавить строгий режим:

```text
Для каждого K-слоя найти фактическую ячейку, XY footprint которой содержит точку X/Y.
```

---

## 3. Технологический стек

Минимальные зависимости:

```text
PySide6
resqpy
h5py
numpy
pandas
openpyxl
pyarrow
shapely
```

Для тестов:

```text
pytest
```

Для будущей сборки в `.exe`:

```text
pyinstaller
```

На первом этапе упаковку в `.exe` не делать. Сначала добиться стабильного чтения `.epc/.h5` и корректного экспорта результатов.

---

## 4. Предлагаемая структура проекта

Создать структуру:

```text
resqml_sleeve_extractor/
│
├── main.py
├── requirements.txt
├── README.md
├── AGENTS.md
│
├── app/
│   ├── __init__.py
│   ├── main_window.py
│   │
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── file_selectors.py
│   │   ├── property_selector.py
│   │   ├── sleeves_table_preview.py
│   │   └── log_panel.py
│   │
│   └── workers/
│       ├── __init__.py
│       ├── load_model_worker.py
│       └── extraction_worker.py
│
├── core/
│   ├── __init__.py
│   ├── resqml_reader.py
│   ├── sleeves_loader.py
│   ├── grid_indexer.py
│   ├── property_extractor.py
│   ├── exporter.py
│   └── validation.py
│
├── scripts/
│   ├── inspect_resqml.py
│   └── test_single_cell_read.py
│
└── tests/
    ├── test_sleeves_loader.py
    ├── test_exporter.py
    └── test_grid_indexer.py
```

---

## 5. Этап 0 — консольная диагностика RESQML

Перед GUI обязательно сделать консольный скрипт:

```text
scripts/inspect_resqml.py
```

Скрипт должен:

1. Принять путь к `.epc`.
2. Открыть модель через `resqpy`.
3. Напечатать список grid objects.
4. Для каждого grid напечатать:
   - title;
   - uuid;
   - размеры `NI/NJ/NK`;
   - тип сетки, если доступен.
5. Напечатать первые 50 grid properties:
   - title;
   - uuid;
   - indexable element;
   - uom;
   - shape, если доступно.
6. Попробовать получить geometry metadata.
7. Не загружать всю геометрию и все свойства целиком.

Пример запуска:

```bash
python scripts/inspect_resqml.py "D:/PetrelExport/model.epc"
```

Ожидаемый результат:

```text
Opened EPC: D:/PetrelExport/model.epc
Found grids: 1

[0] Grid title: ...
UUID: ...
NI/NJ/NK: 120 x 200 x 80

Properties:
[0] PORO
[1] PERM
[2] NTG
...
```

Если этот скрипт не работает, GUI пока не писать.

---

## 6. Этап 1 — GUI MVP

Создать главное окно PySide6 с вкладками:

```text
1. Model
2. Sleeves
3. Properties
4. Run
5. Preview / QC
```

### 6.1. Вкладка Model

Функции:

- выбор `.epc`;
- кнопка `Load model`;
- список найденных grids;
- отображение:
  - grid title;
  - UUID;
  - `NI/NJ/NK`;
  - путь к `.epc`;
  - путь к связанному `.h5`, если можно определить.

### 6.2. Вкладка Sleeves

Функции:

- загрузка CSV/XLSX;
- preview первых 100 строк;
- выбор колонок через dropdown:
  - `Sleeve_ID`;
  - `X`;
  - `Y`;
  - `Well`, optional;
  - `Stage`, optional;
  - `MD`, optional;
  - `TVD`, optional.
- валидация:
  - нет пустых `X/Y`;
  - `X/Y` приводятся к float;
  - есть уникальный идентификатор муфты;
  - предупреждение о дубликатах.

### 6.3. Вкладка Properties

Функции:

- список grid properties с чекбоксами;
- поиск по имени свойства;
- кнопки:
  - `Select all`;
  - `Clear`;
  - `Select visible`;
- отображать metadata свойства:
  - title;
  - UUID;
  - indexable element;
  - uom.

### 6.4. Вкладка Run

Функции:

- выбор режима:

```text
Sampling mode:
[x] Fast column mode
[ ] Strict vertical intersection mode  // пока disabled или TODO
```

- active cells:

```text
[x] Skip inactive cells
[ ] Include inactive cells with IsActive flag
```

- output:

```text
[x] CSV
[ ] XLSX
[ ] Parquet
```

- выбор папки/файла результата;
- кнопки:
  - `Run extraction`;
  - `Cancel`;
- progress bar;
- log panel.

### 6.5. Вкладка Preview / QC

Показывать:

- первые 1000 строк результата;
- количество загруженных муфт;
- количество обработанных муфт;
- количество муфт вне грида;
- количество извлечённых строк;
- количество пропущенных inactive cells;
- список ошибок и предупреждений.

---

## 7. Модули core

### 7.1. `core/resqml_reader.py`

Задачи:

- открыть `.epc`;
- создать объект `resqpy.model.Model`;
- найти grids;
- получить размеры grid;
- получить список grid properties;
- вернуть metadata без чтения всех массивов;
- предоставить методы для доступа к выбранному grid/property.

Предлагаемые классы:

```python
@dataclass
class GridInfo:
    index: int
    title: str
    uuid: str
    ni: int
    nj: int
    nk: int

@dataclass
class PropertyInfo:
    index: int
    title: str
    uuid: str
    indexable_element: str | None
    uom: str | None
    property_kind: str | None
```

Класс:

```python
class ResqmlReader:
    def __init__(self, epc_path: str): ...
    def open(self) -> None: ...
    def list_grids(self) -> list[GridInfo]: ...
    def select_grid(self, grid_uuid: str) -> None: ...
    def list_properties(self) -> list[PropertyInfo]: ...
    def get_grid_shape(self) -> tuple[int, int, int]: ...
    def get_property_value(self, property_uuid: str, i: int, j: int, k: int): ...
```

Важно: `get_property_value()` не должен читать всё свойство целиком, если можно прочитать только нужное значение/срез.

---

### 7.2. `core/sleeves_loader.py`

Задачи:

- читать CSV/XLSX;
- нормализовать названия колонок;
- проверить обязательные поля;
- вернуть DataFrame.

Функции:

```python
def load_sleeves_table(path: str) -> pd.DataFrame: ...

def validate_sleeves_table(
    df: pd.DataFrame,
    sleeve_col: str,
    x_col: str,
    y_col: str,
) -> list[str]: ...
```

---

### 7.3. `core/grid_indexer.py`

Задачи:

- найти колонку грида по X/Y;
- вернуть список ячеек по вертикали.

Для MVP:

```python
class FastGridIndexer:
    def __init__(self, grid): ...

    def build_column_index(self) -> None:
        """
        Построить быстрый индекс XY-колонок.
        Не загружать чрезмерно большие массивы без необходимости.
        """

    def find_column(self, x: float, y: float) -> tuple[int, int] | None:
        """
        Найти ближайшую или содержащую I/J колонку.
        На первом этапе допустим nearest-column mode.
        """

    def vertical_cells(self, x: float, y: float) -> list[tuple[int, int, int]]:
        """
        Вернуть [(i, j, k), ...] по всем K.
        """
```

Для версии 2 оставить интерфейс:

```python
class StrictGridIndexer:
    def __init__(self, grid): ...

    def find_cells_intersected_by_vertical_line(
        self,
        x: float,
        y: float,
    ) -> list[tuple[int, int, int]]:
        """
        TODO:
        Для каждого K найти фактическую ячейку, polygon footprint которой содержит X/Y.
        """
```

---

### 7.4. `core/property_extractor.py`

Задачи:

- принять список муфт;
- принять выбранные свойства;
- по каждой муфте получить вертикальные ячейки;
- вытащить значения свойств;
- вернуть или потоково записать результат.

Предлагаемый интерфейс:

```python
@dataclass
class ExtractionSettings:
    sampling_mode: str
    skip_inactive: bool
    batch_size: int
    selected_property_uuids: list[str]

class PropertyExtractor:
    def __init__(self, reader: ResqmlReader, indexer, settings: ExtractionSettings): ...

    def extract_for_sleeves(
        self,
        sleeves_df: pd.DataFrame,
        progress_callback=None,
        log_callback=None,
        cancel_callback=None,
    ):
        ...
```

Не держать весь результат в памяти для больших расчётов. Для MVP можно возвращать DataFrame для малых тестов, но предусмотреть streaming writer.

---

### 7.5. `core/exporter.py`

Задачи:

- CSV export;
- XLSX export;
- Parquet export;
- streaming CSV writer;
- предупреждение по Excel limit.

Функции:

```python
def export_csv(df: pd.DataFrame, path: str) -> None: ...
def export_xlsx(df: pd.DataFrame, path: str) -> None: ...
def export_parquet(df: pd.DataFrame, path: str) -> None: ...
```

Для больших результатов добавить:

```python
class StreamingCsvExporter:
    def __init__(self, path: str, columns: list[str]): ...
    def write_rows(self, rows: list[dict]) -> None: ...
    def close(self) -> None: ...
```

---

### 7.6. `core/validation.py`

Задачи:

- проверка путей;
- проверка выбранных свойств;
- проверка колонок таблицы муфт;
- проверка выходного файла;
- оценка числа строк результата.

---

## 8. Основной алгоритм MVP

```python
# 1. Открыть RESQML
reader = ResqmlReader(epc_path)
reader.open()
reader.select_grid(grid_uuid)

# 2. Загрузить муфты
sleeves_df = load_sleeves_table(sleeves_path)

# 3. Создать indexer
indexer = FastGridIndexer(reader.grid)
indexer.build_column_index()

# 4. Настройки
settings = ExtractionSettings(
    sampling_mode="fast",
    skip_inactive=True,
    batch_size=500,
    selected_property_uuids=[...],
)

# 5. Извлечение
extractor = PropertyExtractor(reader, indexer, settings)
extractor.extract_for_sleeves(
    sleeves_df=sleeves_df,
    progress_callback=...,
    log_callback=...,
    cancel_callback=...,
)
```

На каждую муфту:

```python
for sleeve in sleeves:
    x = sleeve["X"]
    y = sleeve["Y"]

    i, j = indexer.find_column(x, y)

    if i is None:
        write_warning("Sleeve outside grid")
        continue

    for k in range(nk):
        if skip_inactive and not reader.cell_is_active(i, j, k):
            continue

        row = {
            "Sleeve_ID": sleeve_id,
            "Well": well,
            "Stage": stage,
            "X": x,
            "Y": y,
            "I": i + 1,
            "J": j + 1,
            "K": k + 1,
            "IsActive": is_active,
            "TVD_top": tvd_top,
            "TVD_base": tvd_base,
            "TVD_center": tvd_center,
        }

        for prop in selected_properties:
            row[prop.title] = reader.get_property_value(prop.uuid, i, j, k)

        exporter.write_row(row)
```

Внутри Python использовать индексы `0-based`. В выходной таблице писать `I/J/K` как `1-based`, чтобы было удобно сравнивать с Petrel.

---

## 9. Строгий режим для версии 2

После MVP добавить режим:

```text
Strict vertical intersection mode
```

Требования:

1. Для каждой муфты `X/Y` и каждого `K` определить фактическую ячейку, чей XY footprint содержит точку.
2. Не предполагать, что `I/J` одинаковые на всех `K`.
3. Использовать spatial index для ускорения.
4. Для ускорения можно:
   - строить индексы по слоям;
   - использовать bounding boxes;
   - затем точную проверку через `shapely.contains` / `covers`.
5. Добавить QC-сравнение fast mode vs strict mode:
   - сколько K-слоёв совпало;
   - сколько отличается;
   - список проблемных муфт.

---

## 10. QC и логирование

Приложение должно сохранять рядом с результатом файл:

```text
extraction_log.txt
```

Содержимое:

```text
EPC path:
H5 path:
Grid title:
Grid UUID:
Grid shape NI/NJ/NK:
Selected properties:
Input sleeves file:
Sleeve ID column:
X column:
Y column:
Sampling mode:
Skip inactive:
Output file:
Started:
Finished:
Number of sleeves:
Sleeves inside grid:
Sleeves outside grid:
Extracted rows:
Skipped inactive cells:
Warnings:
Errors:
```

В GUI показывать те же ключевые метрики.

---

## 11. Обработка ошибок

Ошибки должны быть понятными для инженера, а не только traceback.

Примеры сообщений:

```text
Не удалось открыть EPC-файл. Проверьте, что рядом лежит связанный HDF5-файл.
В таблице муфт не найдена колонка X.
Координаты X/Y содержат пустые или текстовые значения.
Для выбранного grid не найдены свойства.
Муфта M001 не попала в footprint модели.
Свойство PORO не удалось прочитать для ячейки I=10 J=15 K=3.
```

Traceback можно писать в log-файл, но в GUI давать короткое понятное сообщение.

---

## 12. Тесты

Минимальные тесты:

### `test_sleeves_loader.py`

- CSV читается;
- XLSX читается;
- отсутствует X;
- отсутствует Y;
- X/Y приводятся к float;
- пустые строки отбрасываются или помечаются.

### `test_exporter.py`

- CSV создаётся;
- XLSX создаётся;
- Parquet создаётся;
- StreamingCsvExporter пишет заголовок и строки.

### `test_grid_indexer.py`

- на синтетической регулярной сетке точка попадает в ожидаемую колонку;
- точка вне сетки возвращает `None`;
- индексы в выходе корректно переводятся из 0-based в 1-based.

---

## 13. Команды запуска

Создание окружения:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Установка зависимостей:

```bash
pip install -r requirements.txt
```

Диагностика RESQML:

```bash
python scripts/inspect_resqml.py "D:/PetrelExport/model.epc"
```

Запуск GUI:

```bash
python main.py
```

Запуск тестов:

```bash
pytest
```

---

## 14. `requirements.txt`

Начальный вариант:

```text
PySide6
resqpy
h5py
numpy
pandas
openpyxl
pyarrow
shapely
pytest
```

---

## 15. Definition of Done для MVP

MVP считается готовым, если:

1. Приложение запускается командой:

```bash
python main.py
```

2. Можно выбрать `.epc`.
3. Приложение показывает хотя бы один grid.
4. Приложение показывает размеры grid.
5. Приложение показывает список properties.
6. Можно загрузить CSV/XLSX с муфтами.
7. Можно выбрать колонки `Sleeve_ID`, `X`, `Y`.
8. Можно выбрать 1–3 свойства.
9. Можно запустить fast extraction.
10. GUI не зависает во время расчёта.
11. Есть progress bar и log panel.
12. Результат сохраняется в CSV.
13. В CSV есть строки вида:

```text
Sleeve_ID, X, Y, I, J, K, TVD_top, TVD_base, TVD_center, Property_1, Property_2, ...
```

14. Есть файл `extraction_log.txt`.
15. Если муфта вне грида, приложение не падает, а пишет предупреждение.

---

## 16. Важные TODO после MVP

После рабочего MVP добавить:

1. Строгий режим пересечения вертикали с corner-point/faulted grid.
2. Parquet export через `pyarrow`.
3. Streaming CSV без накопления результата в RAM.
4. Разбиение XLSX на листы или предупреждение по лимиту Excel.
5. Сохранение/загрузка настроек проекта.
6. Визуальный QC:
   - карта муфт поверх grid footprint;
   - подсветка муфт вне модели;
   - histogram extracted property values.
7. PyInstaller-сборка в `.exe`.
8. Логирование через стандартный `logging`, а не только print.

---

## 17. Стиль кода

Требования:

- Python 3.11+.
- Использовать type hints.
- Использовать dataclasses для простых структур.
- Логику не смешивать с GUI.
- GUI вызывает core-модули через workers.
- Не использовать глобальные переменные для состояния модели.
- Исключения перехватывать на границе worker → GUI.
- Все функции, работающие с большими массивами, должны быть явно написаны с учётом памяти.

Плохой стиль:

```python
# Плохо: GUI напрямую читает HDF5 и считает всё внутри обработчика кнопки
def on_run_clicked(self):
    huge_array = h5_dataset[:]
```

Хороший стиль:

```python
# Хорошо: GUI запускает worker, worker использует core-логику
def on_run_clicked(self):
    self.worker = ExtractionWorker(settings)
    self.worker.progress.connect(self.progress_bar.setValue)
    self.worker.log.connect(self.log_panel.append)
    self.worker.start()
```

---

## 18. Первое действие агента

Начни не с GUI, а с консольной диагностики.

Сначала создай:

```text
requirements.txt
scripts/inspect_resqml.py
core/resqml_reader.py
```

После этого реализуй минимальный запуск:

```bash
python scripts/inspect_resqml.py path/to/model.epc
```

Только когда диагностика успешно показывает grids/properties, переходи к PySide6 GUI.
