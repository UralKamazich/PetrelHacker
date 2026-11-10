// UI language switch (RU / EN).
//
// The interface is written in English; Russian is applied on top of the DOM:
// every text node and the placeholder/title/aria-label attributes are looked up
// in RU (exact phrases) and RU_PATTERNS (templated messages). A MutationObserver
// translates everything the app renders later (status line, lists, errors), and
// the English originals are kept so switching back to EN restores them.
// Data is never translated: inputs, column/well/file selects and the containers
// listed in I18N_SKIP keep their values as they are.

const I18N_STORAGE_KEY = 'petrelhacker.lang';
const I18N_ATTRIBUTES = ['placeholder', 'title', 'aria-label'];
const I18N_SKIP = [
  'script', 'style', 'textarea', 'input',
  'select:not([data-i18n-options])',
  '#metrics-properties', '#property-table', '#well-table-body', '.wells-page-list',
  '.merge-file-name', '.merge-summary td', '.help-window', '.js-plotly-plot .hovertext',
  '[data-no-i18n]'
];

const RU = {
  // Sidebar and pages
  'RESQML / Rescue extractor': 'Выгрузка RESQML / Rescue',
  'Models': 'Модели',
  'Wells': 'Скважины',
  'Sections': 'Разрезы',
  'Extraction': 'Выгрузка',
  'Curves / QC': 'Кривые / QC',
  'Metrics': 'Метрики',
  'Merge': 'Объединение',
  'Logs': 'Журнал',
  'Ready': 'Готово',
  'Attention': 'Внимание',
  'Error': 'Ошибка',
  'Python backend idle': 'Python-бэкенд свободен',

  // Models
  'Load models': 'Загрузить модели',
  'Sources': 'Источники',
  'Properties': 'Свойства',
  'All': 'Все',
  'None': 'Ничего',
  'Select Petrel model': 'Выбрать модель Petrel',
  'Petrel model': 'Модель Petrel',
  'Model': 'Модель',
  'no properties selected': 'свойства не выбраны',
  'reloaded all': 'перезагружены все',

  // Wells
  'Frac-list sleeves, column mapping and model trajectory matching.': 'Муфты frac-list, сопоставление колонок и траекторий моделей.',
  'Frac-list': 'Frac-list',
  'Frac-list XLSX / CSV': 'Frac-list XLSX / CSV',
  'Load frac-list': 'Загрузить frac-list',
  'No frac-list loaded': 'Frac-list не загружен',
  'No frac-list selected': 'Frac-list не выбран',
  'Required column mapping': 'Сопоставление обязательных колонок',
  'Target field -> column in file': 'Поле -> колонка в файле',
  'Select frac-list first': 'Сначала выберите frac-list',
  'Overwrite all X/Y': 'Перезаписать все X/Y',
  'Calculate and save X/Y': 'Рассчитать и сохранить X/Y',
  'Wells and sleeves': 'Скважины и муфты',
  'Filter wells': 'Фильтр скважин',
  'No sleeves loaded': 'Муфты не загружены',
  'Match wells': 'Сопоставить скважины',
  'Load selected wells': 'Загрузить выбранные скважины',
  'Load all wells': 'Загрузить все скважины',
  'Frac-list well': 'Скважина frac-list',
  'Model trajectory': 'Траектория модели',
  'Load JSON': 'Загрузить JSON',
  'Save JSON': 'Сохранить JSON',
  'Apply': 'Применить',
  'Close': 'Закрыть',
  'Well matching JSON': 'JSON сопоставления скважин',
  'Unnamed well': 'Скважина без имени',
  'Trajectory': 'Траектория',
  'Coordinates': 'Координаты',
  'Bottom MD': 'MD забоя',
  'Max angle': 'Макс. угол',
  'Azimuth 500 m': 'Азимут 500 м',

  // Sections
  'Model slice from top to base along a selected well trajectory.': 'Разрез модели от кровли до подошвы вдоль выбранной траектории.',
  'Section workspace': 'Рабочая папка разрезов',
  'No workspace selected': 'Рабочая папка не выбрана',
  'No saved section workspace': 'Нет сохранённой рабочей папки разрезов',
  'Saved sections': 'Сохранённые разрезы',
  'No saved sections': 'Нет сохранённых разрезов',
  'New section': 'Новый разрез',
  'Open workspace': 'Открыть папку',
  'Data': 'Данные',
  'Well trajectory': 'Траектория скважины',
  'Well': 'Скважина',
  'Port': 'Порт',
  'Property': 'Свойство',
  'Named surfaces': 'Поверхности',
  'Sample step, m': 'Шаг выборки, м',
  'X axis': 'Ось X',
  'Horizontal distance': 'Горизонтальное расстояние',
  '3D distance along well': '3D-расстояние вдоль ствола',
  'Horizontal distance, m': 'Горизонтальное расстояние, м',
  'Horizontal distance along trajectory projection, m': 'Горизонтальное расстояние по проекции траектории, м',
  '3D distance along well, m': '3D-расстояние вдоль ствола, м',
  'MD, m': 'MD, м',
  'Skip inactive cells': 'Пропускать неактивные ячейки',
  'Draw section': 'Построить разрез',
  'Draw': 'Построить',
  'Clear cache': 'Очистить кэш',
  'Auto boundaries': 'Авто-границы',
  'Boundary gap, m': 'Склейка, м',
  'Min layer, m': 'Мин. пласт, м',
  'Show boundary points': 'Показывать точки границ',
  'Add local barrier points': 'Добавлять точки локальных барьеров',
  'Boundary file': 'Файл границ',
  'Save': 'Сохранить',
  'Save PNG': 'Сохранить PNG',
  'Copy image': 'Копировать',
  'Hover over a section cell': 'Наведите курсор на ячейку разреза',
  'Top total': 'Кровля total',
  'Bot total': 'Подошва total',
  'Top local': 'Кровля local',
  'Bot local': 'Подошва local',
  'TVD top': 'TVD кровли',
  'No section data': 'Нет данных разреза',
  'Select Section workspace folder': 'Выберите рабочую папку разрезов',
  'Select a workspace containing saved sections.': 'Выберите папку с сохранёнными разрезами.',
  'Saved section snapshots with editable boundary points.': 'Сохранённые разрезы с редактируемыми точками границ.',
  'Saved sections index': 'Список сохранённых разрезов',

  // Extraction
  'Export selected model properties for frac-list sleeves.': 'Выгрузка выбранных свойств моделей для муфт frac-list.',
  'Run extraction': 'Запустить выгрузку',
  'Input summary': 'Сводка входных данных',
  'Selected': 'Выбрано',
  'Sleeves': 'Муфты',
  'Rows': 'Строки',
  'Run options': 'Параметры запуска',
  'Output XLSX / CSV': 'Результат XLSX / CSV',
  'Write property diagnostics': 'Писать диагностику свойств',
  'Parallel workers': 'Параллельных процессов',
  'Model coverage': 'Покрытие моделями',
  'Check coverage': 'Проверить покрытие',
  'Not checked': 'Не проверено',
  'All sleeves inside.': 'Все муфты внутри.',
  'No sleeves inside: its columns will be empty.': 'Ни одной муфты внутри: колонки будут пустыми.',
  'Coverage check applies to the Models source.': 'Проверка покрытия относится к источнику «Модели».',

  // Curves
  'Four overlaid channels with independent scales and depth shift.': 'Четыре наложенных канала с независимыми шкалами и сдвигом по глубине.',
  'Extracted table': 'Таблица выгрузки',
  'Load table': 'Загрузить таблицу',
  'Depth mode': 'Режим глубины',
  'Common grid': 'Общая сетка',
  'Individual cell': 'Каждая ячейка',
  'Depth min': 'Глубина мин',
  'Depth max': 'Глубина макс',
  'Value min': 'Значение мин',
  'Value max': 'Значение макс',
  'No stage': 'Нет стадии',
  'Previous stage (←)': 'Предыдущая стадия (←)',
  'Next stage (→)': 'Следующая стадия (→)',
  'Min': 'Мин',
  'Max': 'Макс',
  'Shift m': 'Сдвиг, м',
  'No curve channels': 'Нет каналов кривых',
  'No curve data': 'Нет данных кривых',

  // Metrics
  'Interval metrics with selected channels and metric families.': 'Интервальные метрики по выбранным каналам и наборам метрик.',
  'Calculate metrics': 'Рассчитать метрики',
  'Inputs': 'Входные данные',
  'Intervals table': 'Таблица интервалов',
  'Output metrics XLSX': 'Файл метрик XLSX',
  'Channels': 'Каналы',
  'Read headers': 'Прочитать заголовки',
  'Lithology': 'Литология',
  'Density': 'Плотность',
  'Reservoir values': 'Значения коллектора',
  'Additional channels': 'Дополнительные каналы',
  'Metric set': 'Набор метрик',
  'Thickness': 'Толщина',
  'Net thickness': 'Эффективная толщина',
  'NTG avg': 'NTG среднее',
  'NTG median': 'NTG медиана',
  'PORO avg': 'PORO среднее',
  'PORO median': 'PORO медиана',
  'PERM arithmetic avg': 'PERM среднее арифм.',
  'PERM geometric avg': 'PERM среднее геом.',
  'PERM median': 'PERM медиана',
  'Additional: avg': 'Доп.: среднее',
  'Additional: arithmetic mean': 'Доп.: среднее арифм.',
  'Additional: geometric mean': 'Доп.: среднее геом.',
  'Additional: median': 'Доп.: медиана',
  'Additional: min': 'Доп.: мин',
  'Additional: max': 'Доп.: макс',
  'Additional: integral': 'Доп.: интеграл',
  'Additional: min*': 'Доп.: мин*',
  'Additional: max*': 'Доп.: макс*',
  'Additional: std': 'Доп.: ст. отклонение',
  'Additional: delta': 'Доп.: дельта',

  // Merge
  'Merge metric tables from different models into one table by two key columns.': 'Объединение таблиц метрик разных моделей в одну по двум ключевым колонкам.',
  'Merge tables': 'Объединить таблицы',
  'Files': 'Файлы',
  'Add files': 'Добавить файлы',
  'Clear': 'Очистить',
  'Keys and output': 'Ключи и результат',
  'Key column 1': 'Ключевая колонка 1',
  'Key column 2': 'Ключевая колонка 2',
  'Output XLSX': 'Результат XLSX',
  'Add Merge_source column': 'Добавить колонку Merge_source',
  'Move up': 'Выше',
  'Move down': 'Ниже',
  'Remove': 'Убрать',
  'Source': 'Источник',
  'File': 'Файл',
  'Rows with own data': 'Строк со своими данными',
  'Reading headers…': 'Чтение заголовков…',
  'Add two or more metric files (XLSX / CSV). The first file sets the column order; if two files have different values in one cell, the value from the upper file is kept.':
    'Добавьте два или больше файлов метрик (XLSX / CSV). Первый файл задаёт порядок колонок; если в одной ячейке у двух файлов разные значения, остаётся значение из файла выше.',

  // Logs
  'Backend progress and diagnostics.': 'Ход работы бэкенда и диагностика.',

  // Busy / status titles and subtitles
  'Loading models': 'Загрузка моделей',
  'Reading properties, wells, and named surfaces': 'Чтение свойств, скважин и поверхностей',
  'Reading trajectories from all models': 'Чтение траекторий всех моделей',
  'Loading sleeves': 'Загрузка муфт',
  'Reading frac-list and wells': 'Чтение frac-list и скважин',
  'Reading frac-list headers': 'Чтение заголовков frac-list',
  'Analyzing frac-list well trajectories': 'Анализ траекторий скважин frac-list',
  'Saving coordinates': 'Сохранение координат',
  'Loading wells': 'Загрузка скважин',
  'Checking coverage': 'Проверка покрытия',
  'Matching sleeves to model footprints': 'Сопоставление муфт с контурами моделей',
  'Extracting': 'Выгрузка',
  'Building output table': 'Формирование таблицы результата',
  'Extraction complete': 'Выгрузка завершена',
  'Extraction cancelled: check Model coverage': 'Выгрузка отменена: проверьте покрытие моделями',
  'Coverage: all models cover all sleeves': 'Покрытие: все модели покрывают все муфты',
  'Reading table': 'Чтение таблицы',
  'Loading headers': 'Загрузка заголовков',
  'Reading headers': 'Чтение заголовков',
  'Calculating metrics': 'Расчёт метрик',
  'Processing intervals': 'Обработка интервалов',
  'Merging tables': 'Объединение таблиц',
  'Reading curves': 'Чтение кривых',
  'Loading table metadata': 'Загрузка описания таблицы',
  'Drawing curves': 'Построение кривых',
  'Drawing section': 'Построение разреза',
  'Sampling model along trajectory': 'Выборка модели вдоль траектории',
  'Loading section': 'Загрузка разреза',
  'Loading section context': 'Загрузка контекста разреза',
  'Loading saved section': 'Загрузка сохранённого разреза',
  'Loading selected well/port': 'Загрузка выбранной скважины/порта',
  'Auto-fitting selected well/port': 'Автоподбор для выбранной скважины/порта',
  'Saving boundaries': 'Сохранение границ',
  'Saved section boundaries': 'Границы разреза сохранены',
  'Opening workspace': 'Открытие рабочей папки',
  'Reading Section workspace': 'Чтение рабочей папки разрезов',
  'Reading Wells selection': 'Чтение выбора скважин',
  'Reading local cache': 'Чтение локального кэша',
  'Clearing section cache': 'Очистка кэша разрезов',
  'Removing saved section rasters': 'Удаление сохранённых растров разрезов',
  'Section cache cleared': 'Кэш разрезов очищен',
  'Section cache saved.': 'Кэш разреза сохранён.',
  'Section image copied to clipboard': 'Картинка разреза скопирована в буфер',
  'Section image copied to clipboard.': 'Картинка разреза скопирована в буфер.',
  'Loaded section from memory cache.': 'Разрез загружен из кэша в памяти.',
  'Loading section directly from disk cache.': 'Разрез загружается напрямую из кэша на диске.',
  'Loading section cache with the current surface selection.': 'Загрузка кэша разреза с текущим выбором поверхностей.',
  'Cached section selected; loading section automatically.': 'Выбран сохранённый разрез; он загружается автоматически.',
  'Temporary cache unavailable; loaded section from persistent workspace.': 'Временный кэш недоступен; разрез загружен из рабочей папки.',
  'Restored scene settings from Section workspace.': 'Настройки сцены восстановлены из рабочей папки разрезов.',
  'Restored section scene settings.': 'Настройки сцены разреза восстановлены.',
  'Total boundaries were not saved': 'Границы Total не сохранены',
  'No file selected': 'Файл не выбран',
  'No wells selected': 'Скважины не выбраны',

  // Errors raised in the renderer
  'Add at least two files to merge.': 'Добавьте хотя бы два файла для объединения.',
  'File headers are still being read.': 'Заголовки файлов ещё читаются.',
  'Select both key columns.': 'Выберите обе ключевые колонки.',
  'Key columns must be different.': 'Ключевые колонки должны различаться.',
  'Enter output file name.': 'Введите имя файла результата.',
  'Output file must differ from the input files.': 'Файл результата должен отличаться от входных файлов.',
  'Enter boundary file name.': 'Введите имя файла границ.',
  'Enter metrics output file name.': 'Введите имя файла метрик.',
  'Draw a section first.': 'Сначала постройте разрез.',
  'Place boundary points first.': 'Сначала расставьте точки границ.',
  'Invalid well matching JSON.': 'Неверный JSON сопоставления скважин.',
  'Load an Excel frac-list before saving a section PNG.': 'Загрузите frac-list Excel перед сохранением PNG разреза.',
  'Load frac-list first.': 'Сначала загрузите frac-list.',
  'Load models first to match wells.': 'Сначала загрузите модели, чтобы сопоставить скважины.',
  'Load models first.': 'Сначала загрузите модели.',
  'Load models, then load wells.': 'Загрузите модели, затем скважины.',
  'Load sleeves first to match wells.': 'Сначала загрузите муфты, чтобы сопоставить скважины.',
  'Load wells and select a trajectory.': 'Загрузите скважины и выберите траекторию.',
  'No saved section workspace was found for this frac-list.': 'Для этого frac-list не найдена рабочая папка разрезов.',
  'No sleeve markers were loaded for this well.': 'Для этой скважины не загружены маркеры муфт.',
  'Saved section does not match the loaded models or current settings. Use Draw section.': 'Сохранённый разрез не соответствует загруженным моделям или настройкам. Нажмите «Построить разрез».',
  'Saved section is unavailable. Use Draw section to rebuild it.': 'Сохранённый разрез недоступен. Нажмите «Построить разрез», чтобы пересоздать его.',
  'Select at least one metric.': 'Выберите хотя бы одну метрику.',
  'Select at least one well.': 'Выберите хотя бы одну скважину.',
  'Select extracted table first.': 'Сначала выберите таблицу выгрузки.',
  'Select frac-list on Extraction page first.': 'Сначала выберите frac-list на странице «Выгрузка».',
  'Select intervals table before metrics output file name.': 'Сначала выберите таблицу интервалов, затем имя файла метрик.',
  'Select section property.': 'Выберите свойство для разреза.',
  'Select sleeves table before output file name.': 'Сначала выберите таблицу муфт, затем имя файла результата.',
  'Select sleeves table first.': 'Сначала выберите таблицу муфт.',
  'Selected trajectory was not found.': 'Выбранная траектория не найдена.',
  'Selected wells have no assigned trajectories.': 'У выбранных скважин нет назначенных траекторий.',
  'Stage was not returned by the backend.': 'Бэкенд не вернул стадию.',
  'The file already contains X/Y data for the selected ports.': 'Файл уже содержит X/Y для выбранных портов.',
  'The selected folder has no saved sections.': 'В выбранной папке нет сохранённых разрезов.',
  'Warning: no model trajectories were matched to selected wells. Use Match wells on the Wells page.':
    'Предупреждение: траектории моделей не сопоставлены с выбранными скважинами. Используйте «Сопоставить скважины» на странице «Скважины».',
  'Warning: no selected Extraction properties were found for Sections.': 'Предупреждение: для разрезов не найдены свойства, выбранные для выгрузки.',
  'Warning: no wells are selected on the Wells page; section well list is empty.': 'Предупреждение: на странице «Скважины» ничего не выбрано; список скважин разреза пуст.',
  'Set the TT/BB points and press Save again.': 'Поставьте точки TT/BB и снова нажмите «Сохранить».',

  // Common backend messages
  'Loading extracted cell table...': 'Загрузка таблицы ячеек...',
  'Loading interval table...': 'Загрузка таблицы интервалов...',
  'Calculating interval metrics...': 'Расчёт интервальных метрик...',
  'Metrics paths are incomplete.': 'Не заданы все пути для метрик.',
  'Select at least two files to merge.': 'Выберите хотя бы два файла для объединения.',
  'Select key columns.': 'Выберите ключевые колонки.',

  'Continue extraction?': 'Продолжить выгрузку?',
  'Clay window, m': 'Окно глин над/под пластом, м',
  'Barrier window, m': 'Окно внутренних барьеров, м',
  'Taken from the big clays above/below the reservoir: TopTotal / BotTotal / Total_pm intervals and cap-clay barriers':
    'Берётся из больших глин над и под пластом: интервалы TopTotal / BotTotal / Total_pm и барьеры-покрышки',
  'Nearest part of an internal barrier (the whole barrier if it is thinner)': 'Ближайшая часть внутреннего барьера (весь барьер, если он тоньше)',
  'Clay window must be a positive number of metres.': 'Окно глин должно быть положительным числом метров.',
  'Barrier window must be a positive number of metres.': 'Окно барьеров должно быть положительным числом метров.',
  'Analyzing lithology codes…': 'Анализ кодов литологии…',
  'Lithology codes by PORO': 'Коды литологии по PORO',
  'Lithology codes by NTG': 'Коды литологии по NTG',
  'Code': 'Код',
  'Cells': 'Ячеек',
  'h, m': 'h, м',
  'PORO mean': 'PORO ср.',
  'NTG mean': 'NTG ср.',
  'Verdict': 'Вывод',
  'reservoir': 'коллектор',
  'non-reservoir': 'неколлектор',
  'Select PORO channel to get a recommendation.': 'Выберите канал PORO, чтобы получить рекомендацию.',
  'No reservoir code found: no code has PORO > 0 in at least half of the cells.': 'Код коллектора не найден: ни у одного кода нет PORO > 0 хотя бы в половине ячеек.',
  'Reservoir values are not set.': 'Значения коллектора не заданы.',
  'Select extracted table and lithology column.': 'Выберите таблицу выгрузки и колонку литологии.',
  'no properties': 'нет свойств'
};

// Templated messages: [English pattern, Russian replacement]. $1… are the captured values;
// captures named in TRANSLATED_GROUPS are translated recursively.
const RU_PATTERNS = [
  [/^Warning: (.+)$/s, 'Предупреждение: $T1'],
  [/^ERROR: (.+)$/s, 'ОШИБКА: $T1'],
  [/^Attention: (.+)$/s, 'Внимание: $T1'],
  [/^Error: (.+)$/s, 'Ошибка: $T1'],
  [/^Metrics rows: (\d+)$/, 'Строк метрик: $1'],
  [/^Merged: (\d+) rows, (\d+) columns$/, 'Объединено: $1 строк, $2 колонок'],
  [/^Merged with (\d+) conflicting cell\(s\): see the summary$/, 'Объединено, конфликтных ячеек: $1 — см. сводку'],
  [/^Merge files: (\d+)$/, 'Файлов для объединения: $1'],
  [/^(\d+) file\(s\) could not be read$/, 'Не удалось прочитать файлов: $1'],
  [/^(\d+) files by (.+)$/, '$1 файла(ов) по $2'],
  [/^(\d+) file\(s\)$/, 'файлов: $1'],
  [/^Cannot read (.+?): (.+)$/, 'Не удалось прочитать $1: $2'],
  [/^Saved: (.+) · (\d+) rows, (\d+) columns$/, 'Сохранено: $1 · $2 строк, $3 колонок'],
  [/^(\d+) columns, (\d+) rows · (.+)$/, '$1 колонок, $2 строк · $3'],
  [/^(\d+) columns · (.+)$/, '$1 колонок · $2'],
  [/^No key column (.+?) · (.+)$/, 'Нет ключевой колонки $1 · $T2'],
  [/^Headers: (\d+)$/, 'Заголовков: $1'],
  [/^Sleeves: (\d+) rows$/, 'Муфт: $1 строк'],
  [/^Sleeves headers: (\d+) columns$/, 'Заголовки муфт: $1 колонок'],
  [/^Curve rows: (\d+)$/, 'Строк кривых: $1'],
  [/^Curve table: (\d+) rows$/, 'Таблица кривых: $1 строк'],
  [/^Section cells: (\d+), sleeves: (\d+)$/, 'Ячеек разреза: $1, муфт: $2'],
  [/^(.+): (\d+) stations, (\d+) cells, (\d+) sleeves$/, '$1: станций $2, ячеек $3, муфт $4'],
  [/^Auto boundaries: (\d+) sleeves, gap (.+) m, min layer (.+) m$/, 'Авто-границы: муфт $1, склейка $2 м, мин. пласт $3 м'],
  [/^Saved boundaries: (\d+) rows(.*)$/, 'Границы сохранены: $1 строк$T2'],
  [/^, skipped (\d+)$/, ', пропущено $1'],
  [/^, PNG: (.+)$/, ', PNG: $1'],
  [/^Saved X\/Y: (\d+) ports in (\d+) well\(s\)$/, 'Сохранены X/Y: $1 портов в $2 скважинах'],
  [/^Wells: (\d+), surfaces: (\d+)$/, 'Скважин: $1, поверхностей: $2'],
  [/^Trajectories: (\d+)$/, 'Траекторий: $1'],
  [/^Selected wells: (\d+)$/, 'Выбрано скважин: $1'],
  [/^Selected well trajectories: (\d+)$/, 'Выбрано траекторий скважин: $1'],
  [/^Well trajectories: (\d+)$/, 'Траекторий скважин: $1'],
  [/^Well matches: (\d+)$/, 'Сопоставлено скважин: $1'],
  [/^Saved well matches: (\d+)$/, 'Сохранено сопоставлений: $1'],
  [/^Loaded well matches: (\d+)(.*)$/, 'Загружено сопоставлений: $1$T2'],
  [/^, selected wells: (\d+)$/, ', выбрано скважин: $1'],
  [/^All wells \((\d+)\)$/, 'Все скважины ($1)'],
  [/^(\d+) of (\d+) wells$/, '$1 из $2 скважин'],
  [/^Well: (.+)$/, 'Скважина: $1'],
  [/^(.+) · Port (.+) \((\d+)\/(\d+)\)$/, '$1 · порт $2 ($3/$4)'],
  [/^(\d+) Petrel models, (\d+) properties in project$/, 'Моделей Petrel: $1, свойств в проекте: $2'],
  [/^(\d+) sections, (\d+) wells, (.+)$/, 'разрезов: $1, скважин: $2, $3'],
  [/^(\d+) wells · (\d+) properties · (.+)$/, 'скважин: $1 · свойств: $2 · $3'],
  [/^Saved (.+) · (\d+) cells$/, 'Сохранено $1 · ячеек: $2'],
  [/^Loaded (\d+) model\(s\) \((.+)\), (\d+) wells, (\d+) surfaces$/, 'Загружено моделей: $1 ($T2), скважин: $3, поверхностей: $4'],
  [/^Keeping loaded models: (.+)$/, 'Остаются загруженными: $1'],
  [/^Coverage: (\d+) model\(s\) do not cover all sleeves$/, 'Покрытие: моделей, не покрывающих все муфты: $1'],
  [/^(\d+) model\(s\) do not cover all selected sleeves\.$/, 'Моделей, не покрывающих все выбранные муфты: $1.'],
  [/^(.+) · (.+): (\d+) of (\d+) sleeves inside\. ?(.*)$/, '$1 · $2: внутри $3 из $4 муфт. $T5'],
  [/^(\d+) sleeve\(s\) outside: empty values for them\.$/, 'Муфт снаружи: $1, для них значения пустые.'],
  [/^(.+) will be empty for (\d+) sleeve\(s\)\.$/, '$1 будут пустыми для $2 муфт.'],
  [/^Extraction complete, but (.+) do not cover all sleeves \(see Model coverage\)$/, 'Выгрузка завершена, но $1 покрывают не все муфты (см. «Покрытие моделями»)'],
  [/^Section PNG saved: (.+)$/, 'PNG разреза сохранён: $1'],
  [/^Section boundaries saved: (.+)$/, 'Границы разреза сохранены: $1'],
  [/^Section workspace updated: (.+)$/, 'Рабочая папка разрезов обновлена: $1'],
  [/^Section cache cleared: (.*)$/, 'Кэш разрезов очищен: $1'],
  [/^Loaded saved section: (.+)$/, 'Загружен сохранённый разрез: $1'],
  [/^Restored section boundary points: (\d+) from (.+)$/, 'Восстановлено точек границ: $1 из $2'],
  [/^TVDSS_TOP_TOTAL\/BOT_TOTAL are missing in Excel for (\d+) sleeve row\(s\)\.$/, 'В Excel нет TVDSS_TOP_TOTAL/BOT_TOTAL для $1 строк муфт.'],
  [/^Well\/port: (.+)\. Set the TT\/BB points and press Save again\.$/, 'Скважина/порт: $1. Поставьте точки TT/BB и снова нажмите «Сохранить».'],
  [/^(\d+) port\(s\) are outside their trajectory MD range\.$/, '$1 портов вне диапазона MD траектории.'],
  [/^(\d+) sleeve row\(s\) were not matched and were not updated\.$/, '$1 строк муфт не сопоставлены и не обновлены.'],
  [/^(\d+) selected well\(s\) were skipped because no trajectory is assigned\.$/, '$1 выбранных скважин пропущено: не назначена траектория.'],
  [/^(\d+) selected well\(s\) to (.+)$/, '$1 выбранных скважин в $2'],
  [/^no well match for "(.+)"\. Use Match wells on the Extraction page\.$/, 'нет сопоставления для «$1». Используйте «Сопоставить скважины».'],
  [/^cannot load trajectories from (.+?): (.+)$/, 'не удалось загрузить траектории из $1: $2'],
  [/^Model source inspect failed: (.+)$/, 'Не удалось прочитать источник модели: $1'],
  [/^State restore failed: (.+)$/, 'Не удалось восстановить состояние: $1'],
  [/^Reading (.+) \((.+)\)\.\.\.$/, 'Чтение $1 ($2)...'],
  [/^Merging (\d+) files by (.+)\.\.\.$/, 'Объединение $1 файлов по $2...'],
  [/^Writing merged table: (.+)$/, 'Запись объединённой таблицы: $1'],
  [/^Writing metrics XLSX: (.+)$/, 'Запись файла метрик: $1'],
  [/^Writing metrics description: (.+)$/, 'Запись описания метрик: $1'],
  [/^(\d+) row\(s\) have identical data in all files \(empty Merge_source\), e\.g\. no metrics in any model\.$/,
    'Строк с одинаковыми данными во всех файлах (пустой Merge_source): $1 — например, ни одна модель не посчитала для них метрики.'],
  [/^(\d+) cell\(s\) have different non-empty values in several files; the value from the first file was kept\. Columns: (.+)$/,
    'Ячеек с разными значениями в нескольких файлах: $1; оставлено значение из первого файла. Колонки: $2'],
  [/^(.+): (\d+) duplicate key row\(s\) ignored \(first kept\): (.+)$/, '$1: повторяющихся ключей $2, взята первая строка: $3'],
  [/^(.+): (\d+) row\(s\) without key values were skipped\.$/, '$1: пропущено строк без ключа: $2.'],
  [/^(.+): key column\(s\) not found: (.+)$/, '$1: не найдены ключевые колонки: $2'],
  [/^(\d+) sleeve\(s\) have no (top|bottom) barrier: (.+)$/, 'У $1 муфт нет барьера ($2): $3'],
  [/^(\d+) barrier side\(s\) have Local more than (.+) m from Total but no internal barrier mark (.+)$/, 'Сторон барьеров, где Local дальше $2 м от Total, но метки барьера нет: $1 $3'],
  [/^(\d+) barrier side\(s\) have TB\/BB marks thicker than (.+)$/, 'Сторон барьеров с метками TB/BB толще $2 при Local у Total (мощность обнулена): $1'],
  [/^(\d+) barrier side\(s\) are near the (.+) tolerance (.+)$/, 'Сторон барьеров у границы допуска $2: $1 $3'],
  [/^(\d+) barrier side\(s\) have no Local\/Total bounds; (.+)$/, 'Сторон барьеров без границ Local/Total: $1; метрики барьера пустые.'],
  [/^(\d+) barrier side\(s\): Local is at the Total boundary \(monolithic\), (.+)$/, 'Сторон барьеров с монолитом (Local у Total, внутреннего барьера нет, взято окно глин-покрышки): $1. Список — в .txt.'],
  [/^(\d+) sleeve barrier\(s\) are near the seal tolerance (.+)$/, 'Барьеров у границы допуска покрышки: $1 $2'],
  [/^(\d+) sleeve barrier\(s\) have zero thickness by TB\/BB points (.+)$/, 'Барьеров с нулевой толщиной по точкам TB/BB: $1 $2'],
  [/^Intervals table has no barrier columns (.+)$/, 'В таблице интервалов нет колонок барьеров $1'],
  [/^Recommended reservoir values: (.+)$/, 'Рекомендуемые значения коллектора: $1'],
  [/^Shmin looks to be in different units in the files \(median (\S+) (.+)\): probably MPa vs atm\. Recalculate the metrics with the same Shmin units before clustering\.$/,
    'Shmin в файлах, похоже, в разных единицах (медиана $1: $2): вероятно, МПа и атм. Пересчитайте метрики с Shmin в одних единицах перед кластеризацией.'],
  [/^Current value (.+) differs from the recommendation\.$/, 'Текущее значение $1 не совпадает с рекомендацией.'],
  [/^Fractional lithology values in (.+) of cells are rounded to the nearest code\.$/, 'Дробные значения литологии у $1 ячеек округлены до ближайшего кода.'],
  [/^Cells inside Total intervals: (\d+)$/, 'Ячеек внутри интервалов Total: $1'],
  [/^All cells: (\d+)$/, 'Все ячейки: $1'],
  [/^(PORO|NTG) > 0$/, '$1 > 0'],
  [/^Lithology column is missing: (.+)$/, 'Нет колонки литологии: $1'],
  [/^Lithology column (.+) has fractional values in (\d+%) of cells \(upscaled property\); they are rounded to the nearest code\.$/,
    'В колонке литологии $1 дробные значения у $2 ячеек (осреднённое свойство); они округлены до ближайшего кода.'],
  [/^No cells have lithology (.+) in reservoir values \((.+)\); Net metrics are empty\.$/,
    'Нет ячеек с литологией $1 из значений коллектора ($2); метрики Net пустые.'],
  [/^Net cells \((.+) in (.+)\) have (PORO|NTG) > 0 only in (\d+%) of cells versus (\d+%) in other cells: the reservoir values look inverted, check the lithology codes\.$/,
    'У ячеек Net ($1 = $2) $3 > 0 только в $4 ячеек, а у остальных — в $5: похоже, значения коллектора перепутаны, проверьте коды литологии.']
];

const i18nOriginals = new WeakMap();
let i18nLanguage = 'ru';
let i18nObserver = null;
let i18nApplying = false;

function i18nTranslate(text) {
  if (text == null) return text;
  const value = String(text);
  if (i18nLanguage !== 'ru' || !/[A-Za-z]/.test(value)) return value;
  const leading = value.match(/^\s*/)[0];
  const trailing = value.match(/\s*$/)[0];
  const core = value.slice(leading.length, value.length - trailing.length);
  const translated = i18nTranslateCore(core);
  return translated === core ? value : leading + translated + trailing;
}

function i18nTranslateCore(core) {
  if (!core) return core;
  if (Object.prototype.hasOwnProperty.call(RU, core)) return RU[core];
  for (const [pattern, replacement] of RU_PATTERNS) {
    const match = core.match(pattern);
    if (!match) continue;
    return replacement.replace(/\$(T?)(\d)/g, (_all, translate, index) => {
      const part = match[Number(index)] == null ? '' : match[Number(index)];
      return translate ? i18nTranslateCore(part) : part;
    });
  }
  // "Title: subtitle" lines written to the log by setBusy().
  const colon = core.indexOf(': ');
  if (colon > 0) {
    const head = core.slice(0, colon);
    if (Object.prototype.hasOwnProperty.call(RU, head)) return `${RU[head]}: ${i18nTranslateCore(core.slice(colon + 2))}`;
  }
  return core;
}

function i18nSkipped(element) {
  return Boolean(element && element.closest && element.closest(I18N_SKIP.join(',')));
}

function i18nTranslateTextNode(node) {
  const parent = node.parentElement;
  if (!parent || i18nSkipped(parent)) return;
  let original = i18nOriginals.get(node);
  // The app changed the text since we translated it: the new text is the new original.
  if (original === undefined || (node.nodeValue !== original.en && node.nodeValue !== original.ru)) {
    original = { en: node.nodeValue, ru: null };
  }
  original.ru = i18nLanguage === 'ru' ? i18nTranslate(original.en) : original.en;
  i18nOriginals.set(node, original);
  const next = i18nLanguage === 'ru' ? original.ru : original.en;
  if (node.nodeValue !== next) node.nodeValue = next;
}

function i18nTranslateAttributes(element) {
  if (i18nSkipped(element) && !(element.matches && element.matches('input, textarea'))) return;
  if (element.closest && element.closest('[data-no-i18n], .help-window')) return;
  let store = i18nOriginals.get(element);
  if (!store) {
    store = {};
    i18nOriginals.set(element, store);
  }
  for (const name of I18N_ATTRIBUTES) {
    if (!element.hasAttribute(name)) continue;
    const current = element.getAttribute(name);
    const saved = store[name];
    if (!saved || (current !== saved.en && current !== saved.ru)) store[name] = { en: current, ru: null };
    store[name].ru = i18nTranslate(store[name].en);
    const next = i18nLanguage === 'ru' ? store[name].ru : store[name].en;
    if (current !== next) element.setAttribute(name, next);
  }
}

function i18nApply(root) {
  if (!root) return;
  i18nApplying = true;
  try {
    if (root.nodeType === Node.TEXT_NODE) {
      i18nTranslateTextNode(root);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) i18nTranslateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      if (node.nodeType === Node.TEXT_NODE) i18nTranslateTextNode(node);
      else i18nTranslateAttributes(node);
      node = walker.nextNode();
    }
  } finally {
    i18nApplying = false;
  }
}

function i18nObserve() {
  if (i18nObserver) return;
  i18nObserver = new MutationObserver(mutations => {
    if (i18nApplying) return;
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') i18nApply(mutation.target);
      else if (mutation.type === 'attributes') i18nApply(mutation.target);
      else mutation.addedNodes.forEach(node => i18nApply(node));
    }
  });
  i18nObserver.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: I18N_ATTRIBUTES
  });
}

function setLanguage(language) {
  i18nLanguage = language === 'en' ? 'en' : 'ru';
  localStorage.setItem(I18N_STORAGE_KEY, i18nLanguage);
  document.documentElement.lang = i18nLanguage;
  document.querySelectorAll('[data-lang]').forEach(button => {
    button.classList.toggle('active', button.dataset.lang === i18nLanguage);
  });
  i18nApply(document.body);
}

// For texts that leave the DOM (native dialogs).
function t(text) {
  return i18nTranslate(text);
}

function i18nDialogOptions(options) {
  const result = Object.assign({}, options);
  ['title', 'message', 'detail', 'buttonLabel', 'confirmLabel', 'cancelLabel'].forEach(key => {
    // Paragraphs are translated one by one (coverage details list one model per paragraph).
    if (typeof result[key] === 'string') result[key] = result[key].split('\n\n').map(t).join('\n\n');
  });
  return result;
}

function initLanguage() {
  document.querySelectorAll('[data-lang]').forEach(button => {
    button.addEventListener('click', () => setLanguage(button.dataset.lang));
  });
  setLanguage(localStorage.getItem(I18N_STORAGE_KEY) || 'ru');
  i18nObserve();
}
