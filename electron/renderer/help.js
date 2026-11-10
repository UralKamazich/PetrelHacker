// Panel help: a "?" button is added to every panel with data-help="<key>".
// Content is static trusted HTML authored here.
const panelHelp = {
  'models-sources': {
    title: 'Models → Sources',
    body: `
      <p>Здесь задаются до трёх моделей (M1, M2, M3), из которых будут читаться свойства.</p>
      <h4>Как заполнить</h4>
      <ol>
        <li>Нажмите <b>...</b> у нужного слота и выберите источник:
          <ul>
            <li><code>.pet</code> — проект Petrel (читается напрямую);</li>
            <li><code>.epc</code> — экспорт RESQML (рядом должен лежать <code>.h5</code> с тем же именем);</li>
            <li>главный <code>.bin</code> Rescue или папку с Rescue-экспортом.</li>
          </ul>
        </li>
        <li>Если в проекте Petrel несколько гридов, рядом с путём появится список моделей: название · размер грида · число свойств. Наведите курсор, чтобы увидеть примеры свойств.</li>
        <li><b>Δz</b> — сдвиг глубин модели в метрах (например, чтобы согласовать модели с разными отметками). По умолчанию 0. Применяется при выгрузке, перезагружать модель не нужно.</li>
        <li>Нажмите <b>Load models</b> в правом верхнем углу экрана. Полоса под моделями показывает реальный ход загрузки: модель и текущий шаг (индекс проекта, гриды, свойства, траектории N из M, анализ скважин frac-list).</li>
      </ol>
      <h4>Догрузка</h4>
      <ul>
        <li>Load models загружает только <b>новые или изменённые</b> модели. Если M1 и M2 уже загружены и вы добавили M3, загрузится только M3.</li>
        <li>Если ничего не менялось, Load models перечитывает все модели — так можно обновить данные после изменения проекта.</li>
      </ul>
      <h4>Советы</h4>
      <ul>
        <li><b>x</b> очищает слот. Пустые слоты просто пропускаются.</li>
        <li>Если одно и то же свойство выбрано из нескольких моделей, в выгрузке колонки получат префиксы <code>M1_</code>, <code>M2_</code>, <code>M3_</code>.</li>
        <li>Пути и выбор сохраняются между запусками приложения.</li>
      </ul>`
  },
  'models-properties': {
    title: 'Models → Properties',
    body: `
      <p>Список свойств (кубов) загруженных моделей. Отмеченные свойства будут выгружены на шаге <b>Extraction</b>.</p>
      <ul>
        <li>Свойства сгруппированы по моделям и папкам проекта Petrel.</li>
        <li><b>All</b> / <b>None</b> — отметить или снять все свойства.</li>
        <li>Выбирайте только то, что понадобится для метрик и QC: каждое свойство добавляет колонки в выгрузку и время расчёта.</li>
        <li>Типовой набор для метрик: NTG, PORO, PERM, литология/фации, Density, Shmin.</li>
      </ul>
      <h4>Преобразования при чтении</h4>
      <ul>
        <li>Проницаемость (в названии есть <code>perm</code>) переводится в мД.</li>
        <li>Плотность из Rescue умножается на 1000, чтобы совпадать с RESQML (~2500).</li>
        <li>Служебные значения NoData выгружаются пустыми ячейками.</li>
      </ul>`
  },
  'wells-fraclist': {
    title: 'Wells → Frac-list',
    body: `
      <p>Загрузка таблицы муфт ГРП (frac-list) и сопоставление её колонок с полями программы.</p>
      <h4>Порядок</h4>
      <ol>
        <li>Нажмите <b>...</b> и выберите файл XLSX или CSV.</li>
        <li>В блоке <b>Required column mapping</b> для каждого поля выберите колонку из файла:
          <ul>
            <li><b>Well *</b> — скважина (обязательно);</li>
            <li><b>Port *</b> — номер муфты/порта/стадии (обязательно);</li>
            <li><b>X</b>, <b>Y</b> — координаты муфты;</li>
            <li><b>TVDSS_PORT</b> — абсолютная глубина муфты;</li>
            <li><b>MD</b> — глубина по стволу (нужна для расчёта X/Y по траектории и для выгрузки из Section workspace).</li>
          </ul>
        </li>
        <li>Нажмите <b>Load frac-list</b> вверху экрана.</li>
      </ol>
      <p>Счётчики внизу: <b>Rows</b> — строк в файле, <b>Wells</b> — скважин, <b>Selected</b> — отмечено скважин, <b>Coordinates</b> — у скольких муфт есть X/Y.</p>
      <h4>Расчёт X/Y по траектории</h4>
      <p>Если в файле нет координат, но есть MD: назначьте скважинам траектории в таблице справа и нажмите <b>Calculate and save X/Y</b>. Координаты будут рассчитаны по MD и записаны прямо в файл frac-list. Флажок <b>Overwrite all X/Y</b> перезаписывает и уже заполненные координаты; без него заполняются только пустые.</p>
      <p>Названия скважин нормализуются: кириллица и латиница одинакового вида (<code>6А031</code> / <code>6A031</code>) считаются одним именем.</p>`
  },
  'wells-table': {
    title: 'Wells → Wells and sleeves',
    body: `
      <p>Таблица скважин из frac-list: выбор скважин для расчёта и привязка к траекториям моделей.</p>
      <h4>Колонки</h4>
      <ul>
        <li><b>Флажок</b> — скважина участвует в выгрузке, разрезах и расчёте X/Y.</li>
        <li><b>Sleeves</b> — число муфт; <b>X/Y</b> — сколько муфт имеют координаты (оранжевым — если не у всех).</li>
        <li><b>Model</b> — модель, из которой брать траекторию. При выборе модели траектория с тем же именем подставляется автоматически.</li>
        <li><b>Trajectory</b> — траектория скважины в модели; выберите вручную, если имена не совпали.</li>
        <li><b>Max angle</b>, <b>Azimuth 500 m</b>, <b>Bottom MD</b> — максимальный зенитный угол, азимут последних 500 м и забой по MD. Удобно для контроля, что выбрана правильная траектория.</li>
      </ul>
      <h4>Кнопки</h4>
      <ul>
        <li>Поле поиска фильтрует список по имени скважины.</li>
        <li><b>All</b> / <b>None</b> — выбрать все или снять выбор.</li>
        <li><b>Save JSON</b> сохраняет привязки скважин к траекториям и выбор скважин в файл; <b>Load JSON</b> восстанавливает их. Удобно, если работаете с тем же месторождением повторно.</li>
      </ul>`
  },
  'extract-summary': {
    title: 'Extraction → Input summary',
    body: `
      <p>Сводка того, что пойдёт в выгрузку: число моделей, выбранных свойств, скважин и муфт, а также имя загруженного frac-list.</p>
      <p>Если какое-то число равно 0 — вернитесь на соответствующий шаг:</p>
      <ul>
        <li><b>Models / Properties</b> — экран Models (загрузите модели и отметьте свойства);</li>
        <li><b>Wells / Sleeves</b> — экран Wells (загрузите frac-list и отметьте скважины).</li>
      </ul>
      <h4>Model coverage</h4>
      <p>Показывает, сколько муфт выбранных скважин попадает в контур каждой модели. Если муфта вне модели, все свойства этой модели для неё будут <b>пустыми</b> — а затем пустыми будут и метрики по ним.</p>
      <ul>
        <li><b>Check coverage</b> — проверить до выгрузки (только для источника Models).</li>
        <li>Зелёный — все муфты внутри; жёлтый — часть муфт снаружи; красный — ни одной муфты внутри, колонки модели будут пустыми.</li>
        <li>При <b>Run extraction</b> проверка выполняется автоматически <b>до</b> выгрузки. Если какая-то модель покрывает не все муфты, появится окно с подробностями — можно продолжить или отменить. Итог также пишется в лог и в <code>extraction_log.txt</code>.</li>
      </ul>
      <p>Если модель не покрывает муфты, загрузите на экране Models другую модель, которая охватывает этот участок.</p>`
  },
  'extract-options': {
    title: 'Extraction → Run options',
    body: `
      <p>Выгрузка свойств по вертикали через каждую муфту. Для каждой муфты по X/Y находится колонка ячеек модели, и по всем ячейкам этой колонки записываются глубины и значения выбранных свойств.</p>
      <h4>Источник данных</h4>
      <ul>
        <li><b>Models</b> — читать свойства прямо из моделей по координатам X/Y муфт.</li>
        <li><b>Section workspace</b> — брать данные из сохранённых разрезов (экран Sections → Save). Требует MD у муфт. Ниже показано, найден ли сохранённый workspace для текущего frac-list.</li>
      </ul>
      <h4>Параметры</h4>
      <ul>
        <li><b>Skip inactive cells</b> — не выгружать неактивные ячейки грида.</li>
        <li><b>Write property diagnostics</b> — для каждого свойства дописывать колонки <code>_Model</code>, <code>_I/_J/_K</code>, <code>_TVD_center</code>, <code>_Depth_KB</code>. Полезно для проверки, но файл становится шире; для финальной выгрузки можно отключить.</li>
        <li><b>Parallel workers</b> — число параллельных потоков расчёта (1–32). Запись файла всё равно идёт в одном потоке.</li>
        <li><b>Output XLSX / CSV</b> — имя выходного файла. Если строк больше лимита Excel (~1 млн), файл автоматически сохраняется как CSV с предупреждением в логе.</li>
      </ul>
      <p>Нажмите <b>Run extraction</b>. После завершения путь к выгрузке автоматически подставится на экранах <b>Metrics</b> и <b>Curves / QC</b>.</p>`
  },
  'metrics-inputs': {
    title: 'Metrics → Inputs',
    body: `
      <p>Файлы для расчёта интервальных метрик.</p>
      <ul>
        <li><b>Extracted table</b> — выгрузка ячеек с экрана Extraction (подставляется автоматически). Обязательные колонки: <code>Well</code>, <code>Port</code>, <code>TVD_top</code>, <code>TVD_base</code>, <code>CellHeight</code>.</li>
        <li><b>Intervals table</b> — таблица интервалов, обычно это frac-list с границами, сохранёнными на экране Sections. Обязательные колонки:
          <code>Well</code>, <code>Port</code>, <code>TVDSS_TOP_TOTAL</code>, <code>TVDSS_BOT_TOTAL</code>, <code>TVDSS_TOP_LOCAL</code>, <code>TVDSS_BOT_LOCAL</code>.</li>
        <li><b>Output metrics XLSX</b> — имя файла результата; сохраняется в папку таблицы интервалов. По умолчанию <code>&lt;имя интервалов&gt;_metrics.xlsx</code>.</li>
        <li><b>Clay window, m</b> (окно глин) — сколько метров брать из больших глин над и под пластом: интервалы TopTotal / BotTotal / Total_pm и барьеры-покрышки (seal, seal_total). По умолчанию 15 м; уменьшите (например, до 5 м), если модель плохо построена выше и ниже целевого интервала.</li>
        <li><b>Barrier window, m</b> (окно барьеров) — сколько метров брать из внутреннего барьера (interlayer); если барьер тоньше — берётся весь. По умолчанию 15 м.</li>
      </ul>
      <p>Ячейки сопоставляются с интервалом по <code>Well</code> + <code>Port</code>; если не нашлись — по X/Y (с точностью 0.001 м). Названия «Скважина», «Муфта», «Порт», «Стадия» распознаются автоматически.</p>
      <p>Рядом с результатом пишется файл <code>.txt</code> с описанием расчёта: какие каналы выбраны, формулы и все предупреждения.</p>
      <p>Подробное описание интервалов и метрик — в справке карточки <b>Metric set</b>.</p>`
  },
  'metrics-channels': {
    title: 'Metrics → Channels',
    body: `
      <p>Фиксированные каналы. Здесь вы указываете, какая колонка выгрузки является NTG, PORO и т.д. В результате колонки <b>всегда называются одинаково</b> (<code>NTG_…</code>, <code>PORO_…</code>, <code>Density_…</code>, <code>Shmin_…</code>), независимо от того, как свойство называлось в модели. Поэтому файлы метрик разных моделей можно собирать в одну таблицу — колонки совпадут.</p>
      <h4>Порядок</h4>
      <ol>
        <li>Нажмите <b>Read headers</b> — списки заполнятся колонками выгрузки, и программа попробует угадать каналы по названию.</li>
        <li>Проверьте и при необходимости поправьте выбор в каждом списке. Пустое значение = канал не используется.</li>
      </ol>
      <h4>Каналы</h4>
      <ul>
        <li><b>NTG</b> — песчанистость; используется как вес в NetThickness, KH, PHIH и для определения Net (NTG &gt; 0).</li>
        <li><b>PORO</b> — пористость. Если NTG не выбран, NTG заменяется маской PORO &gt; 0 (1 или 0).</li>
        <li><b>PERM</b> — проницаемость. Если не выбрана, колонки PERM_*, KH остаются пустыми.</li>
        <li><b>Lithology</b> — литология/фации; работает вместе с <b>Reservoir values</b>.</li>
        <li><b>PORO</b>, <b>PERM</b>, <b>Density</b>, <b>Shmin</b> — кроме базовых метрик, считаются по набору «Additional» метрик (для всех интервалов, включая барьеры): <code>PORO_&lt;метрика&gt;_&lt;интервал&gt;</code>, <code>PERM_&lt;метрика&gt;_&lt;интервал&gt;</code>.</li>
        <li><b>Density</b>, <b>Shmin</b> — считаются по набору «Additional» метрик (avg, median, min, max…) и пишутся как <code>Density_&lt;метрика&gt;_&lt;интервал&gt;</code>, <code>Shmin_&lt;метрика&gt;_&lt;интервал&gt;</code>. Если канал не выбран, колонки всё равно создаются пустыми — структура файла не меняется.</li>
      </ul>
      <h4>Reservoir values</h4>
      <p>Коды литологии, которые считаются коллектором, через запятую, например <code>1</code>. Если заданы литология и коды — Net определяется по литологии (это приоритетнее NTG и PORO). Значение запоминается.</p>
      <p>Проверьте код коллектора по модели: у ячеек коллектора есть пористость и NTG &gt; 0. В моделях 3А/5А/6А коллектор — <code>1</code>, а <code>0</code> и <code>2</code> — неколлектор. Если у ячеек Net почти нет пористости, после расчёта внизу страницы появится красное предупреждение «Проверьте определение Net».</p>
      <p>Дробные значения литологии (осреднённое свойство, например 0.9999) округляются до ближайшего целого кода.</p>
      <h4>Рекомендация кода коллектора</h4>
      <p>Когда выбраны таблица выгрузки и литология, под полем Reservoir values появляется таблица по каждому коду литологии (ячейки внутри интервалов Total): число ячеек, мощность, доля ячеек с PORO &gt; 0, средние PORO и NTG. Код считается коллектором, если PORO &gt; 0 хотя бы у половины его ячеек (без канала PORO — по NTG). Кнопка <b>Применить</b> подставляет рекомендованные коды; если текущее значение отличается, это подсвечивается красным.</p>
      <p>Колонки, выбранные здесь, не считаются повторно в Additional channels.</p>`
  },
  'metrics-additional': {
    title: 'Metrics → Additional channels',
    body: `
      <p>Любые другие свойства из выгрузки, по которым нужно посчитать статистику (например, модуль Юнга, Пуассон, UCS).</p>
      <ul>
        <li>В расчёт идут <b>только отмеченные</b> каналы. Ничего не отмечено — дополнительных колонок не будет.</li>
        <li>Список заполняется после <b>Read headers</b> в карточке Channels. Показываются только свойства, выбранные на экране Models (служебные и диагностические колонки скрыты).</li>
        <li>Колонки называются по исходному имени: <code>&lt;свойство&gt;_&lt;метрика&gt;_&lt;интервал&gt;</code>, например <code>M1_YME_STA_avg_Total</code>. Поэтому у разных моделей они могут отличаться — если канал нужен во всех моделях одинаково, его лучше сделать фиксированным.</li>
        <li>В файле результата дополнительные каналы стоят <b>справа</b> от фиксированных (NTG/PORO/PERM → Density → Shmin → дополнительные).</li>
        <li>Каждый канал даёт до 11 метрик × 15 интервалов = 165 колонок. Отмечайте только нужное.</li>
      </ul>`
  },
  'metrics-set': {
    title: 'Metrics → Metric set: расписание метрик',
    wide: true,
    body: `
      <p>Здесь выбирается, какие метрики считать. Ниже — полное описание: по каким интервалам, по каким ячейкам и по каким формулам считается каждая колонка.</p>

      <h4>1. Интервалы (8 штук)</h4>
      <p>Границы берутся из таблицы интервалов (Intervals table) для каждой муфты:</p>
      <table>
        <tr><th>Суффикс</th><th>От</th><th>До</th></tr>
        <tr><td><code>Total</code></td><td>TVDSS_TOP_TOTAL</td><td>TVDSS_BOT_TOTAL</td></tr>
        <tr><td><code>Local</code></td><td>TVDSS_TOP_LOCAL</td><td>TVDSS_BOT_LOCAL</td></tr>
        <tr><td><code>Total_pm&lt;N&gt;m</code></td><td>TVDSS_TOP_TOTAL − N</td><td>TVDSS_BOT_TOTAL + N</td></tr>
        <tr><td><code>TopTotal_m&lt;N&gt;m</code></td><td>TVDSS_TOP_TOTAL − N</td><td>TVDSS_TOP_TOTAL</td></tr>
        <tr><td><code>BotTotal_p&lt;N&gt;m</code></td><td>TVDSS_BOT_TOTAL</td><td>TVDSS_BOT_TOTAL + N</td></tr>
        <tr><td><code>TopBarrier</code></td><td colspan="2">окно барьера над Local (см. ниже)</td></tr>
        <tr><td><code>BotBarrier</code></td><td colspan="2">окно барьера под Local</td></tr>
        <tr><td><code>LocalBarriers</code></td><td colspan="2">Local вместе с TopBarrier и BotBarrier</td></tr>
      </table>
      <p><b>N — окно глин</b> (поле «Окно глин над/под пластом» в карточке Inputs, по умолчанию 15 м): сколько метров берётся из больших глин над и под пластом. Имя интервала содержит окно, например при 5 м — <code>TopTotal_m5m</code>; окна пишутся в колонки <code>CLAY_WINDOW_M</code> / <code>BARRIER_WINDOW_M</code>, поэтому при объединении файлов с разными окнами это будет видно. Уменьшайте окно, если модель плохо построена выше и ниже целевого интервала. <b>Окно барьеров</b> (по умолчанию 15 м) — сколько берётся из внутреннего барьера (interlayer).</p>
      <p><b>Total</b> (раньше назывался Global) — пласт целиком, <b>Local</b> — пропласток у муфты (точки TT/BT и TL/BL на экране Sections). Если внутренних барьеров нет и пласт монолитный, Local совпадает с Total. Три интервала с окном глин N м — окружение пласта: всё вместе, кровля и подошва (глины-покрышки).</p>
      <p>Метки ставятся и корректируются вручную, поэтому расстояния до <b>1 м</b> считаются совпадением — и между Local и Total, и между Local и метками барьеров TB/BB. Для каждой стороны Local (тип — в <code>BARRIER_TOP_KIND</code> / <code>BARRIER_BOT_KIND</code>, мощность внутреннего барьера после допуска — в <code>BARRIER_TOP_LOCAL</code> / <code>BARRIER_BOT_LOCAL</code>):</p>
      <ul>
        <li><b>seal</b> — Local не дальше 1 м от Total: пласт с этой стороны монолитный, мощность внутреннего барьера = 0 (даже если метки TB/BB дают больше), метрики — по ближайшему окну глин (N м) глины-покрышки.</li>
        <li><b>interlayer</b> — Local дальше 1 м от Total и по меткам есть внутренний барьер толще 1 м: мощность = TVDSS_TOP_LOCAL − TVDSS_TOP_BARRIER_LOCAL (снизу TVDSS_BOT_BARRIER_LOCAL − TVDSS_BOT_LOCAL), метрики — по ближайшему окну барьеров (по всему барьеру, если он тоньше).</li>
        <li><b>seal_total</b> — Local дальше 1 м от Total, но барьера по меткам нет: метки не согласованы, мощность = 0, метрики — по окну глин (N м) за границей Total. Такие муфты выводятся для проверки.</li>
        <li><b>none</b> — нет границ Local; метрики барьера пустые.</li>
      </ul>
      <p>Метрики считаются для всех интервалов, даже если они совпадают (например, Local = Total — тогда и метрики одинаковые).</p>
      <h4>Контрасты напряжений (канал Shmin)</h4>
      <p><code>SC_&lt;набор&gt;_Top|Bot_&lt;вариант&gt;</code> = статистика Shmin в барьере (ячейки NonNet) − статистика Shmin в пласте (ячейки Net). Больше нуля — барьер держит трещину.</p>
      <ul>
        <li><b>Наборы:</b> <code>Local</code> — пласт Local и барьеры TopBarrier / BotBarrier (при Local = Total это глины-покрышки); <code>Total</code> — весь пласт Total и глины TopTotal_m15m / BotTotal_p15m (если рвётся весь Total).</li>
        <li><b>Варианты (пласт / барьер):</b> <code>MinMax</code> — min / max; <code>MinStarMaxStar</code> — min* / max*; <code>MinStarMedian</code> — min* / медиана; <code>MedianMedian</code> — медиана / медиана.</li>
        <li><code>SC_&lt;набор&gt;_Asym_&lt;вариант&gt;</code> = контраст снизу − контраст сверху; больше нуля — трещина склонна расти вверх.</li>
        <li><code>SCxH_Local_Top|Bot_&lt;вариант&gt;</code> = контраст × мощность окна барьера — «прочность» барьера.</li>
      </ul>
      <p>Варианты с max чувствительны к отдельным ячейкам с высоким напряжением; для кластеризации устойчивее варианты с медианой барьера. Shmin во всех моделях должен быть в одних единицах (атм или МПа) — при объединении файлов это проверяется.</p>
      <p>После расчёта внизу страницы красным выводятся муфты для проверки: <b>метка без барьера</b> (seal_total), <b>барьер обнулён</b> (метки дают барьер, но Local у Total), <b>у границы допуска</b> (расстояние 0.5–3 м) и <b>монолит</b> (Local у Total, внутреннего барьера нет). Полный список — в <code>.txt</code> рядом с файлом метрик.</p>
      <p>Ячейки, частично попадающие в интервал, учитываются только своей частью: <b>h</b> = мощность пересечения ячейки с интервалом.</p>

      <h4>2. Выборки внутри интервала (×3)</h4>
      <table>
        <tr><th>Суффикс</th><th>Какие ячейки</th></tr>
        <tr><td><i>(без суффикса)</i></td><td>все ячейки интервала</td></tr>
        <tr><td><code>_Net</code></td><td>коллектор</td></tr>
        <tr><td><code>_NonNet</code></td><td>всё, что не вошло в Net</td></tr>
      </table>
      <p>Как определяется Net (по приоритету):</p>
      <ol>
        <li>выбраны Lithology и Reservoir values → ячейки с литологией из списка кодов;</li>
        <li>иначе выбран NTG → ячейки с NTG &gt; 0;</li>
        <li>иначе выбран PORO → ячейки с PORO &gt; 0;</li>
        <li>иначе все ячейки считаются Net (в логе будет предупреждение).</li>
      </ol>
      <p>Итого 5 интервалов × 3 выборки = <b>15 суффиксов</b> на каждую метрику, например
        <code>PORO_avg_Total</code>, <code>PORO_avg_Total_Net</code>, <code>PORO_avg_Total_NonNet</code>, <code>PORO_avg_Local</code>, …</p>

      <h4>3. Имена колонок</h4>
      <p><code>&lt;Канал&gt;_&lt;метрика&gt;_&lt;интервал&gt;[_Net|_NonNet]</code></p>
      <p>Порядок колонок в файле: сначала все колонки таблицы интервалов (Well, Port, X, Y, границы…), затем базовые метрики (Thickness … PHIH) по всем 15 суффиксам, затем <code>Density_*</code>, затем <code>Shmin_*</code>, затем дополнительные каналы. Старые колонки метрик, если они были в таблице интервалов, удаляются и считаются заново.</p>

      <h4>4. Базовые метрики (каналы NTG / PORO / PERM)</h4>
      <table>
        <tr><th>Галочка</th><th>Колонка</th><th>Формула</th></tr>
        <tr><td>Thickness</td><td><code>Thickness_*</code></td><td>Σ h — мощность интервала</td></tr>
        <tr><td>Net thickness</td><td><code>NetThickness_*</code></td><td>Σ (h · NTG). Не пишется для суффиксов <code>_Net</code>. Без NTG — маска PORO &gt; 0; без обоих — пусто</td></tr>
        <tr><td>NTG avg</td><td><code>NTG_avg_*</code></td><td>Σ (NTG · h) / Σ h</td></tr>
        <tr><td>NTG median</td><td><code>NTG_median_*</code></td><td>медиана NTG по ячейкам (без веса)</td></tr>
        <tr><td>PORO avg</td><td><code>PORO_avg_*</code></td><td>Σ (PORO · h) / Σ h</td></tr>
        <tr><td>PORO median</td><td><code>PORO_median_*</code></td><td>медиана PORO</td></tr>
        <tr><td>PERM arithmetic avg</td><td><code>PERM_avg_arith_*</code></td><td>Σ (PERM · h) / Σ h</td></tr>
        <tr><td>PERM geometric avg</td><td><code>PERM_avg_geom_*</code></td><td>exp(Σ (ln PERM · h) / Σ h), только PERM &gt; 0</td></tr>
        <tr><td>PERM median</td><td><code>PERM_median_*</code></td><td>медиана PERM</td></tr>
        <tr><td>KH</td><td><code>KH_*</code></td><td>Σ (PERM · h · NTG); без NTG — маска PORO &gt; 0; без PORO множитель 1</td></tr>
        <tr><td>PHIH</td><td><code>PHIH_*</code></td><td>Σ (PORO · h · NTG); правила те же, что у KH</td></tr>
      </table>

      <h4>5. Метрики Density, Shmin и дополнительных каналов</h4>
      <p>Галочки «Additional: …» применяются ко всем каналам этого типа: Density, Shmin и выбранным в Additional channels. Обозначение <i>value</i> — значение канала в ячейке.</p>
      <table>
        <tr><th>Галочка</th><th>Колонка</th><th>Формула</th></tr>
        <tr><td>avg</td><td><code>&lt;канал&gt;_avg_*</code></td><td>Σ (value · h) / Σ h — средневзвешенное по мощности</td></tr>
        <tr><td>arithmetic mean</td><td><code>&lt;канал&gt;_mean_arith_*</code></td><td>то же, что avg (Σ (value · h) / Σ h)</td></tr>
        <tr><td>geometric mean</td><td><code>&lt;канал&gt;_geom_*</code></td><td>exp(Σ (ln value · h) / Σ h), только value &gt; 0</td></tr>
        <tr><td>median</td><td><code>&lt;канал&gt;_median_*</code></td><td>медиана (без веса)</td></tr>
        <tr><td>min / max</td><td><code>&lt;канал&gt;_min_*</code>, <code>_max_*</code></td><td>минимум / максимум</td></tr>
        <tr><td>integral</td><td><code>&lt;канал&gt;_integral_*</code></td><td>Σ (value · h)</td></tr>
        <tr><td>min*</td><td><code>&lt;канал&gt;_min_star_*</code></td><td>среднее нижних 10 % значений после удаления выбросов (правило 1.5 · IQR)</td></tr>
        <tr><td>max*</td><td><code>&lt;канал&gt;_max_star_*</code></td><td>среднее верхних 10 % значений после удаления выбросов</td></tr>
        <tr><td>std</td><td><code>&lt;канал&gt;_std_*</code></td><td>стандартное отклонение, взвешенное по h</td></tr>
        <tr><td>delta</td><td><code>&lt;канал&gt;_delta_*</code></td><td>max* − min* — устойчивый размах (контраст)</td></tr>
      </table>

      <h4>6. Обработка данных</h4>
      <ul>
        <li>Пустые и нечисловые значения не участвуют в статистике.</li>
        <li>Если в выборке нет валидных значений — ячейка результата пустая (Thickness, integral, KH, PHIH в этом случае = 0).</li>
        <li>median, min, max, min*, max* не взвешиваются по мощности; остальные метрики используют h.</li>
        <li>Если для муфты не нашлось ячеек или нет границ интервала — строка остаётся, метрики пустые, причина пишется в лог и в <code>.txt</code>.</li>
      </ul>

      <h4>7. Сколько будет колонок</h4>
      <p>Каждая отмеченная метрика даёт 15 колонок на канал. Пример: 11 базовых метрик = до 165 колонок; Density + Shmin по 11 метрик = 330 колонок; каждый дополнительный канал — ещё до 165. Если нужен компактный файл — оставьте только нужные галочки (например avg, median, min*, max*, delta).</p>`
  },
  'merge-files': {
    title: 'Merge → Files',
    body: `
      <p>Объединение таблиц метрик, посчитанных по разным моделям, в одну таблицу.</p>
      <ul>
        <li><b>Add files</b> — выбрать два и больше файла XLSX/CSV (можно несколько сразу).</li>
        <li>Порядок важен: ↑ ↓ меняют приоритет. Первый файл задаёт порядок колонок; если в одной ячейке у двух файлов разные непустые значения, остаётся значение из файла выше, а расхождение попадает в предупреждения.</li>
        <li>✕ — убрать файл из списка; исходные файлы не меняются.</li>
      </ul>
      <p>Обычно каждая модель считает метрики только для своих скважин, а остальные строки frac-list у неё пустые. Объединение берёт для каждой ячейки первое непустое значение, поэтому метрики всех моделей собираются в одну строку на муфту.</p>`
  },
  'merge-options': {
    title: 'Merge → Keys and output',
    body: `
      <p><b>Key column 1/2</b> — колонки, по которым сопоставляются строки (по умолчанию <code>Well</code> и <code>Port</code>). В списке только колонки, которые есть во всех файлах.</p>
      <p>При сравнении ключей не важны регистр и пробелы по краям, <code>3</code> и <code>3.0</code> считаются одинаковыми, кириллица и латиница одинакового написания (<code>6А031</code> / <code>6A031</code>) тоже. В результат ключ пишется так, как в первом файле, где встретилась строка.</p>
      <p>Строки, которых нет в одном из файлов, всё равно попадают в результат (объединение всех строк). Повторяющиеся ключи внутри файла: берётся первая строка, остальные отмечаются в предупреждениях.</p>
      <p><b>Output XLSX</b> — путь или имя файла результата; имя без папки сохраняется рядом с первым файлом. По умолчанию — общее начало имён файлов + <code>merged.xlsx</code>.</p>
      <p><b>Merge_source</b> — колонка в конце таблицы: из каких файлов взяты собственные данные строки (например <code>3А</code>). Подпись файла — отличающаяся часть его имени. Пусто — во всех файлах строка одинаковая (например, ни одна модель не посчитала для неё метрики).</p>`
  },
  'curves-data': {
    title: 'Curves / QC → Data',
    body: `
      <p>Просмотр выгрузки в виде каротажных кривых по одной муфте — для проверки свойств и границ.</p>
      <ol>
        <li><b>Extracted table</b> — выгрузка с экрана Extraction (подставляется автоматически). Нажмите <b>Load table</b>.</li>
        <li>Выберите <b>Well</b> и <b>Port</b>.</li>
        <li>Выберите до четырёх каналов (<b>Channel 1–4</b>). Для каждого можно задать шкалу <b>Min/Max</b> (пусто = автоматически) и сдвиг по глубине <b>Shift m</b>.</li>
        <li><b>Draw</b> перерисовывает график.</li>
      </ol>
      <h4>Depth mode</h4>
      <ul>
        <li><b>Common grid</b> — все каналы на общей сетке глубин выгрузки (<code>TVD_top</code>).</li>
        <li><b>Individual cell</b> — каждый канал по глубине центров своих исходных ячеек (<code>&lt;канал&gt;_TVD_center</code>, нужны диагностические колонки). Удобно для сравнения разных моделей/форматов.</li>
      </ul>
      <h4>Экспресс-просмотр стадий</h4>
      <ul>
        <li>Кнопки <b>◀ ▶</b> над графиком (или стрелки <b>← →</b> на клавиатуре) — предыдущая / следующая стадия. После последней стадии скважины автоматически открывается первая стадия следующей скважины.</li>
        <li>Подпись между кнопками: скважина · порт (номер стадии из общего числа).</li>
        <li>Следующие стадии подгружаются заранее в фоне, поэтому листание почти мгновенное. Стрелки клавиатуры не работают, пока курсор стоит в текстовом или числовом поле.</li>
      </ul>
      <p><b>Depth min/max</b> задают диапазон глубин. Масштаб можно менять и мышью прямо на графике — значения в полях обновятся. Если в выгрузке есть границы интервалов, они рисуются горизонтальными линиями.</p>`
  },
  'sections-data': {
    title: 'Sections → Data',
    wide: true,
    body: `
      <p>Разрез модели вдоль траектории скважины и расстановка границ интервалов для метрик (Total/Local).</p>
      <h4>Источник</h4>
      <ul>
        <li><b>New section</b> — построить новый разрез из загруженных моделей.</li>
        <li><b>Saved sections</b> — открыть ранее сохранённые разрезы (section workspace) без загрузки моделей.</li>
      </ul>
      <h4>Построение разреза</h4>
      <ol>
        <li><b>Load selected wells</b> — загрузить траектории скважин, отмеченных на экране Wells; <b>Load all wells</b> — все траектории моделей.</li>
        <li>Выберите <b>Well trajectory</b> и <b>Property</b>. Для авторасстановки границ берите свойство, где коллектор ≠ 0 (NTG, литология, PORO).</li>
        <li><b>Named surfaces</b> — отметьте поверхности, которые нужно показать на разрезе.</li>
        <li><b>Sample step, m</b> — шаг отбора вдоль ствола. <b>Skip inactive cells</b> — не показывать неактивные ячейки.</li>
        <li>Нажмите <b>Draw section</b>. Повторно открытые разрезы берутся из кэша мгновенно.</li>
      </ol>
      <h4>Отображение</h4>
      <ul>
        <li><b>Depth min/max</b>, <b>Value min/max</b> — диапазон глубин и цветовой шкалы.</li>
        <li><b>X axis</b> — горизонтальное расстояние, 3D-расстояние вдоль ствола или MD.</li>
        <li>Колесо мыши — масштаб; перетаскивание по осям: середина оси сдвигает, края оси растягивают. Наведение на ячейку показывает её значения под графиком.</li>
      </ul>
      <h4>Границы интервалов</h4>
      <ul>
        <li><b>Auto boundaries</b> — для каждой муфты по колонке разреза находятся тела коллектора (значение свойства ≠ 0):
          <ul>
            <li><b>TT/BT</b> (Total) — кровля первого и подошва последнего тела;</li>
            <li><b>TL/BL</b> (Local) — тело, ближайшее к муфте;</li>
            <li><b>Boundary gap, m</b> — неколлектор тоньше этого значения внутри тела считается частью тела (склейка);</li>
            <li><b>Min layer, m</b> — коллектор тоньше этого значения отбрасывается.</li>
          </ul>
        </li>
        <li><b>Add local barrier points</b> — дополнительно ставит <b>TB/BB</b>: внешние границы непродуктивных барьеров над и под локальным телом (и их мощность).</li>
        <li>Любую точку можно перетащить мышью по вертикали. <b>Show boundary points</b> скрывает/показывает точки.</li>
        <li><b>Boundary file</b> — имя файла, куда сохраняются границы; по умолчанию <code>&lt;frac-list&gt;_boundaries.xlsx</code> рядом с frac-list (копия frac-list с колонками <code>TVDSS_TOP/BOT_TOTAL</code>, <code>TVDSS_TOP/BOT_LOCAL</code> и барьерами).</li>
        <li><b>Save</b> — записать границы текущей скважины, сохранить разрез в workspace и PNG рядом. Этот файл автоматически становится таблицей интервалов на экране Metrics. Если для какой-то муфты не заданы границы Total — появится предупреждение.</li>
        <li><b>Clear cache</b> — удалить кэш разрезов (если модель изменилась).</li>
      </ul>
      <p>Вверху экрана: <b>Save PNG</b> — сохранить картинку разреза, <b>Copy image</b> — скопировать её в буфер обмена.</p>`
  }
};

function installPanelHelp() {
  document.querySelectorAll('[data-help]').forEach(panel => {
    const help = panelHelp[panel.dataset.help];
    if (!help || panel.querySelector(':scope > .panel-help-button')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'panel-help-button';
    button.textContent = '?';
    button.title = 'Справка';
    button.setAttribute('aria-label', `Справка: ${help.title}`);
    button.addEventListener('click', () => showPanelHelp(help));
    panel.appendChild(button);
  });
}

// Floating, non-modal help window: the app stays usable underneath, so the
// user can follow the instructions step by step. One window is reused.
let panelHelpWindow = null;
let panelHelpPosition = null;

function showPanelHelp(help) {
  if (!panelHelpWindow) panelHelpWindow = createPanelHelpWindow();
  const win = panelHelpWindow;
  win.classList.toggle('wide', Boolean(help.wide));
  win.querySelector('.help-window-title').textContent = help.title;
  const body = win.querySelector('.help-body');
  body.innerHTML = help.body;
  body.scrollTop = 0;
  if (!win.isConnected) document.body.appendChild(win);
  win.style.width = '';
  win.style.height = '';
  placePanelHelpWindow(win);
}

function createPanelHelpWindow() {
  const win = document.createElement('div');
  win.className = 'help-window';
  win.setAttribute('role', 'dialog');
  win.innerHTML = `
    <div class="help-window-header" title="Перетащите, чтобы переместить">
      <div class="help-window-title"></div>
      <button class="icon-button" type="button" aria-label="Закрыть">x</button>
    </div>
    <div class="help-body"></div>
  `;
  win.querySelector('.icon-button').addEventListener('click', () => win.remove());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && win.isConnected) win.remove();
  });
  bindPanelHelpDrag(win, win.querySelector('.help-window-header'));
  window.addEventListener('resize', () => {
    if (win.isConnected) placePanelHelpWindow(win);
  });
  return win;
}

function placePanelHelpWindow(win) {
  const rect = win.getBoundingClientRect();
  const position = panelHelpPosition || {
    left: window.innerWidth - rect.width - 24,
    top: 24
  };
  win.style.left = `${clampHelpCoordinate(position.left, window.innerWidth - rect.width)}px`;
  win.style.top = `${clampHelpCoordinate(position.top, window.innerHeight - rect.height)}px`;
}

function clampHelpCoordinate(value, max) {
  return Math.max(0, Math.min(value, Math.max(0, max)));
}

function bindPanelHelpDrag(win, handle) {
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button')) return;
    const rect = win.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;
    handle.setPointerCapture(event.pointerId);
    win.classList.add('dragging');
    const move = moveEvent => {
      const left = clampHelpCoordinate(moveEvent.clientX - offsetX, window.innerWidth - rect.width);
      const top = clampHelpCoordinate(moveEvent.clientY - offsetY, window.innerHeight - rect.height);
      win.style.left = `${left}px`;
      win.style.top = `${top}px`;
      panelHelpPosition = { left, top };
    };
    const stop = () => {
      win.classList.remove('dragging');
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', stop);
      handle.removeEventListener('pointercancel', stop);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', stop);
    handle.addEventListener('pointercancel', stop);
    event.preventDefault();
  });
}
