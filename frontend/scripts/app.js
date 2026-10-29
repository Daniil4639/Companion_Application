(async () => {
    const Date = CompanionTime.Date;
    try {
        await CompanionProfile.ready;
    } catch (error) {
        document.querySelector('#error-notice').hidden = false;
        document.querySelector('#error-text').textContent = error.message;
        document.querySelector('#retry').onclick = () => location.reload();
        document.querySelector('#new-event').disabled = true;
        document.querySelector('#journal-add').disabled = true;
        document.querySelector('#journal-add-task').disabled = true;
        return;
    }
    if (!CompanionProfile.preview && !CompanionProfile.user) return;

    const C = CompanionCalendar, A = CompanionAPI, D = CompanionDialogs, I = CompanionIcons.icon, E = C.escape;
    const $ = (s, root = document) => root.querySelector(s);
    const storage = {
        get: (key, fallback) => {
            try {
                const v = localStorage.getItem('companion.' + key);
                return v === null ? fallback : JSON.parse(v);
            } catch {
                return fallback;
            }
        }, set: (key, value) => {
            try {
                localStorage.setItem('companion.' + key, JSON.stringify(value));
            } catch {
            }
        }
    };
    const state = {
        page: 'schedule',
        view: 'week',
        anchor: C.dayStart(new Date()),
        mini: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
        occurrences: [],
        today: [],
        hourHeight: Number(storage.get('density', 64)),
        startHour: Number(storage.get('startHour', 8)),
        scroll: null,
        generation: 0,
        controller: null,
        series: [],
        listGeneration: 0
    };
    if (![48, 64, 80].includes(state.hourHeight)) state.hourHeight = 64;
    if (![0, 6, 8, 9].includes(state.startHour)) state.startHour = 8;
    const zone = CompanionTime.zone;
    let toastTimer;

    function toast(message) {
        const el = $('#toast');
        el.textContent = message;
        el.classList.add('visible');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => el.classList.remove('visible'), 4500);
    }

    window.CompanionUI = {toast};

    function setError(message) {
        $('#error-text').textContent = message || '';
        $('#error-notice').hidden = !message;
        document.body.classList.toggle('disconnected', !!message);
    }

    function category(o) {
        return CompanionCategories[o.category] || CompanionCategories.default;
    }

    function setNav(collapsed, persist = true) {
        document.body.classList.toggle('nav-collapsed', collapsed);
        const b = $('#nav-toggle');
        b.setAttribute('aria-expanded', String(!collapsed));
        b.title = collapsed ? 'Развернуть меню' : 'Свернуть меню';
        b.setAttribute('aria-label', b.title);
        if (persist) storage.set('navCollapsed', collapsed);
    }

    function setJournal(collapsed, persist = true) {
        const content = $('#journal-content');
        if (collapsed && content.contains(document.activeElement)) $('#journal-toggle').focus();
        document.body.classList.toggle('journal-collapsed', collapsed);
        content.inert = collapsed;
        content.hidden = collapsed;
        const b = $('#journal-toggle');
        b.setAttribute('aria-expanded', String(!collapsed));
        b.title = collapsed ? 'Открыть панель дня' : 'Свернуть панель дня';
        b.setAttribute('aria-label', b.title);
        if (persist) storage.set('dayPanelCollapsed', collapsed);
    }

    CompanionIcons.mount();
    setNav(storage.get('navCollapsed', innerWidth < 1280), false);
    setJournal(storage.get('dayPanelCollapsed', true), false);
    document.documentElement.style.setProperty('--hour-height', state.hourHeight + 'px');
    $('#nav-toggle').onclick = () => setNav(!document.body.classList.contains('nav-collapsed'));
    $('#journal-toggle').onclick = () => setJournal(!document.body.classList.contains('journal-collapsed'));
    document.addEventListener('pointerdown', e => {
        if (innerWidth <= 1050 && !document.body.classList.contains('journal-collapsed') && !e.target.closest('#journal, dialog')) setJournal(true, false);
    });
    $('#timezone-label').textContent = zone.replaceAll('_', ' ');
    $('#settings-zone').textContent = zone.replaceAll('_', ' ');
    $('#density').value = state.hourHeight;
    $('#start-hour').value = state.startHour;
    $('#density').onchange = e => {
        const ratio = state.hourHeight;
        state.hourHeight = Number(e.target.value);
        if (state.scroll !== null) state.scroll = state.scroll / ratio * state.hourHeight;
        storage.set('density', state.hourHeight);
        document.documentElement.style.setProperty('--hour-height', state.hourHeight + 'px');
        toast('Плотность расписания сохранена');
    };
    $('#start-hour').onchange = e => {
        state.startHour = Number(e.target.value);
        state.scroll = state.startHour * state.hourHeight;
        storage.set('startHour', state.startHour);
        toast('Начальное время сохранено');
    };
    const newEvent = () => {
        const now = new Date(), start = C.dayStart(state.anchor);
        if (C.sameDay(start, now)) {
            start.setHours(now.getHours(), Math.ceil(now.getMinutes() / 30) * 30, 0, 0);
        } else start.setHours(9, 0, 0, 0);
        D.form(start);
    };
    $('#new-event').onclick = newEvent;
    $('#journal-add').onclick = () => {
        const now = new Date();
        const start = new Date(now);
        start.setMinutes(Math.ceil(now.getMinutes() / 30) * 30, 0, 0);
        D.form(start);
    };
    $('#journal-add-task').onclick = () => CompanionTaskDialog.create('TODO', C.dateKey(new Date()));
    if (A.preview) {
        $('#preview-notice').hidden = false;
        [$('#new-event'), $('#journal-add'), $('#journal-add-task')].forEach(b => {
            b.disabled = true;
            b.title = 'Добавление доступно в запущенном приложении';
        });
    }
    document.querySelectorAll('[data-page]').forEach(b => b.onclick = () => showPage(b.dataset.page));
    $('.brand').onclick = e => {
        e.preventDefault();
        showPage('schedule');
    };

    function showPage(page) {
        if (!['schedule', 'events', 'tasks', 'settings'].includes(page)) page = 'schedule';
        storage.set('currentPage', page);
        state.page = page;
        state.listGeneration++;
        document.querySelectorAll('[data-page]').forEach(b => {
            const active = b.dataset.page === page;
            b.classList.toggle('active', active);
            if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
        for (const name of ['schedule', 'events', 'settings', 'tasks']) $('#' + name + '-page').hidden = name !== page;
        const titles = {schedule: 'Расписание', events: 'Все события', settings: 'Настройки', tasks: 'Задачи'};
        const subtitles = {
            schedule: 'Место для планов, встреч и маленьких радостей.',
            events: 'Всё, что вы доверили своему дневнику.',
            settings: 'Пусть дневник подстраивается под вас.',
            tasks: 'От первой идеи до завершённого дела.'
        };
        $('#page-title').innerHTML = E(titles[page]);
        $('#page-subtitle').textContent = subtitles[page];
        document.title = titles[page] + ' · Folliant';
        $('#new-event').hidden = page === 'settings' || page === 'tasks';
        $('#reload-schedule').hidden = page !== 'schedule';
        if (page === 'schedule') {
            renderCalendar();
            loadSchedule();
        }
        if (page === 'events') loadSeries();
        if (page === 'tasks') CompanionTasks.load();
        if (page === 'settings') {
            CompanionMCPSettings.load();
            CompanionLLMSettings.load();
        }
    }

    function syncMini() {
        state.mini = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1);
    }

    function jump(date) {
        state.anchor = C.dayStart(date);
        state.view = 'week';
        syncMini();
        showPage('schedule');
        if (innerWidth <= 1050) setJournal(true, false);
    }

    document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => {
        state.view = button.dataset.view;
        renderCalendar();
        loadSchedule();
    });

    function step(direction) {
        state.anchor = C.navigate(state.anchor, state.view, direction);
        syncMini();
        renderCalendar();
        loadSchedule();
    }

    $('#previous').onclick = () => step(-1);
    $('#next').onclick = () => step(1);
    $('#today').onclick = () => {
        state.scroll = Math.max(0, new Date().getHours() - 1) * state.hourHeight;
        jump(new Date());
    };
    $('#retry').onclick = () => state.page === 'events' ? loadSeries() : loadSchedule();
    $('#reload-events').onclick = () => loadSeries();
    $('#reload-schedule').onclick = () => loadSchedule();
    $('#load-more').onclick = () => loadSeries(true);
    $('#mini-previous').onclick = () => {
        state.mini = new Date(state.mini.getFullYear(), state.mini.getMonth() - 1, 1);
        renderMini();
    };
    $('#mini-next').onclick = () => {
        state.mini = new Date(state.mini.getFullYear(), state.mini.getMonth() + 1, 1);
        renderMini();
    };
    $('#mini-title').onclick = () => {
        state.anchor = new Date(state.mini);
        state.view = 'months';
        showPage('schedule');
        if (innerWidth <= 1050) setJournal(true, false);
    };

    function renderCalendar() {

        document.querySelectorAll('[data-view]').forEach(b => {
            const selected = b.dataset.view === state.view;
            b.classList.toggle('selected', selected);
            b.setAttribute('aria-pressed', String(selected));
        });
        const a = state.anchor, view = $('#calendar-view');
        const labels = {
            week: ['Предыдущая неделя', 'Следующая неделя'],
            months: ['Предыдущий год', 'Следующий год'],
            years: ['Предыдущие 12 лет', 'Следующие 12 лет']
        };
        $('#previous').setAttribute('aria-label', labels[state.view][0]);
        $('#next').setAttribute('aria-label', labels[state.view][1]);
        if (state.view === 'week') {
            const first = C.weekStart(a), last = C.addDays(first, 6);
            const fmt = d => d.toLocaleDateString('ru-RU', {day: 'numeric', month: 'short'}).replace('.', '');
            $('#range-label').textContent = fmt(first) + ' — ' + fmt(last) + ' ' + last.getFullYear();
            renderWeek(view, first);
            $('#calendar-hint').textContent = 'Нажмите на свободное время, чтобы добавить событие';
        } else if (state.view === 'months') {
            $('#range-label').textContent = a.getFullYear() + ' год';
            view.innerHTML = '<div class="picker-scroll"><div class="picker-intro"><h2>Выберите месяц</h2><p>Маленькие главы большого года</p></div><div class="month-picker">' + C.MONTHS.map((month, index) => {
                const current = new Date().getFullYear() === a.getFullYear() && new Date().getMonth() === index;
                return '<button class="month-card ' + (current ? 'current' : '') + '" data-month="' + index + '" aria-label="' + month + ' ' + a.getFullYear() + '"><span class="month-title">' + month + (current ? '<small>сейчас</small>' : '') + '</span><span class="month-dots" aria-hidden="true">' + C.WEEKDAYS.map(d => '<span class="mini-weekday">' + d + '</span>').join('') + C.monthGrid(a.getFullYear(), index).map(d => '<span class="' + (d.getMonth() !== index ? 'faded ' : '') + (C.sameDay(d, new Date()) ? 'today-number' : '') + '">' + d.getDate() + '</span>').join('') + '</span></button>';
            }).join('') + '</div></div>';
            view.querySelectorAll('[data-month]').forEach(b => b.onclick = () => jump(C.selectMonth(a.getFullYear(), Number(b.dataset.month))));
            $('#calendar-hint').textContent = 'Выберите месяц, чтобы перейти к его первой неделе';
        } else {
            const first = C.yearPage(a.getFullYear());
            $('#range-label').textContent = first + ' — ' + (first + 11);
            view.innerHTML = '<div class="picker-scroll"><div class="picker-intro"><h2>Выберите год</h2><p>У каждой истории есть продолжение</p></div><div class="year-picker">' + Array.from({length: 12}, (_, i) => first + i).map(year => '<button class="year-card ' + (year === new Date().getFullYear() ? 'current' : '') + '" data-year="' + year + '"><b>' + year + '</b><small>' + (year === new Date().getFullYear() ? 'ТЕКУЩИЙ ГОД' : '') + '</small></button>').join('') + '</div></div>';
            view.querySelectorAll('[data-year]').forEach(b => b.onclick = () => {
                state.anchor = new Date(Number(b.dataset.year), state.anchor.getMonth(), 1);
                state.view = 'months';
                syncMini();
                renderCalendar();
                loadSchedule();
            });
            $('#calendar-hint').textContent = 'Выберите год, чтобы открыть его месяцы';
        }
        renderMini();
        CompanionTasks.loadCalendar(C.weekStart(state.anchor), C.addDays(C.weekStart(state.anchor), 6), renderMini);
    }

    function renderWeek(view, first) {
        const days = Array.from({length: 7}, (_, i) => C.addDays(first, i)), now = new Date();
        view.innerHTML = '<div class="week-scroll" id="week-scroll"><div class="week-inner"><div class="week-head"><div class="time-caption">24 ЧАСА</div>' + days.map((d, i) => '<button class="day-heading ' + (C.sameDay(d, now) ? 'is-today ' : '') + (C.sameDay(d, state.anchor) ? 'selected-day ' : '') + (i >= 5 ? 'weekend' : '') + '" data-day="' + i + '" aria-label="' + E(d.toLocaleDateString('ru-RU', {
            weekday: 'long',
            day: 'numeric',
            month: 'long'
        })) + '"><span>' + C.WEEKDAYS[i] + '</span><b>' + d.getDate() + '</b></button>').join('') + '</div><div class="week-body"><div class="time-axis" aria-hidden="true">' + Array.from({length: 25}, (_, h) => '<span class="hour-label" style="top:' + (h * state.hourHeight) + 'px">' + C.pad(h) + ':00</span>').join('') + '</div>' + days.map((d, i) => '<div class="day-column ' + (C.sameDay(d, now) ? 'is-today ' : '') + (i >= 5 ? 'weekend' : '') + '" data-column="' + i + '" tabindex="0" aria-label="' + E(d.toLocaleDateString('ru-RU', {
            weekday: 'long',
            day: 'numeric',
            month: 'long'
        })) + ', Enter — добавить событие"></div>').join('') + '</div></div></div>';
        view.querySelectorAll('[data-day]').forEach(b => b.onclick = () => {
            state.anchor = days[Number(b.dataset.day)];
            syncMini();
            renderCalendar();
        });
        view.querySelectorAll('[data-column]').forEach(col => {
            col.onclick = e => {
                if (e.target.closest('.event-card')) return;
                const minutes = Math.min(1410, Math.max(0, Math.floor((e.clientY - col.getBoundingClientRect().top) / state.hourHeight * 2) * 30));
                const date = new Date(days[Number(col.dataset.column)]);
                date.setMinutes(minutes);
                D.form(date);
            };
            col.onkeydown = e => {
                if (e.target !== col || e.key !== 'Enter') return;
                e.preventDefault();
                const date = new Date(days[Number(col.dataset.column)]);
                date.setHours(9);
                D.form(date);
            };
        });
        const scroll = $('#week-scroll');
        scroll.scrollTop = state.scroll ?? state.startHour * state.hourHeight;
        scroll.onscroll = () => state.scroll = scroll.scrollTop;
        drawEvents();
        drawNow();
    }

    function drawEvents() {
        const first = C.weekStart(state.anchor);
        document.querySelectorAll('[data-column]').forEach(col => {
            col.querySelectorAll('.event-card').forEach(b => b.remove());
            const date = C.addDays(first, Number(col.dataset.column));
            for (const item of C.layoutEvents(state.occurrences, date, state.hourHeight)) {
                const o = item.event, cat = category(o), start = new Date(o.start_at), end = new Date(o.finish_at),
                    button = document.createElement('button');
                button.className = 'event-card' + (item.height < 48 ? ' compact' : '') + (item.lanes > 1 ? ' narrow' : '');
                button.style.setProperty('--event-color', cat.color);
                button.style.setProperty('--event-bg', cat.background);
                button.style.top = item.top + 'px';
                button.style.height = item.height + 'px';
                button.style.left = 'calc(' + (item.lane / item.lanes * 100) + '% + 3px)';
                button.style.width = 'calc(' + (100 / item.lanes) + '% - 6px)';
                const label = (item.continuesBefore ? '← ' : '') + C.time(start) + ' — ' + C.time(end) + (item.continuesAfter ? ' →' : '');
                button.innerHTML = '<span class="event-heading">' + I(cat.icon) + '<span class="event-title">' + E(o.title) + '</span></span><span class="event-time">' + E(label) + '</span>';
                button.title = o.title + ' · ' + label;
                button.setAttribute('aria-label', button.title);
                button.onclick = e => {
                    e.stopPropagation();
                    D.details(o);
                };
                col.append(button);
            }
        });
    }

    function drawNow() {
        document.querySelectorAll('.current-time').forEach(el => el.remove());
        const now = new Date(), first = C.weekStart(state.anchor);
        for (const col of document.querySelectorAll('[data-column]')) if (C.sameDay(C.addDays(first, Number(col.dataset.column)), now)) {
            const line = document.createElement('div');
            line.className = 'current-time';
            line.style.top = (now.getHours() + now.getMinutes() / 60) * state.hourHeight + 'px';
            line.title = 'Сейчас ' + C.time(now);
            col.append(line);
        }
    }

    function renderMini() {
        const today = new Date(), first = C.weekStart(state.anchor), end = C.addDays(first, 7);
        $('#mini-title').textContent = C.MONTHS[state.mini.getMonth()] + ' ' + state.mini.getFullYear();
        $('#mini-days').innerHTML = C.monthGrid(state.mini.getFullYear(), state.mini.getMonth()).map(d => {
            const has = CompanionTasks.hasDate(C.dateKey(d)) || state.today.some(o => new Date(o.start_at) < C.addDays(d, 1) && new Date(o.finish_at) > d) || state.occurrences.some(o => new Date(o.start_at) < C.addDays(d, 1) && new Date(o.finish_at) > d);
            return '<button data-date="' + C.dateKey(d) + '" class="' + (d.getMonth() !== state.mini.getMonth() ? 'outside ' : '') + (d >= first && d < end ? 'in-week ' : '') + (C.sameDay(d, today) ? 'is-today ' : '') + (C.sameDay(d, state.anchor) ? 'selected-day ' : '') + (has ? 'has-event' : '') + '" aria-label="' + E(d.toLocaleDateString('ru-RU', {
                day: 'numeric',
                month: 'long',
                year: 'numeric'
            })) + '"' + (C.sameDay(d, today) ? ' aria-current="date"' : '') + '>' + d.getDate() + '</button>';
        }).join('');
        $('#mini-days').querySelectorAll('button').forEach(b => b.onclick = () => jump(new Date(b.dataset.date + 'T12:00:00')));
    }

    function renderToday(failed = false) {
        const now = new Date();
        $('#today-label').textContent = now.toLocaleDateString('ru-RU', {
            weekday: 'long',
            day: 'numeric',
            month: 'long'
        });
        $('#today-count').textContent = failed ? '—' : state.today.length;
        const container = $('#today-events');
        container.innerHTML = '';
        if (!state.today.length) {
            container.innerHTML = '<div class="agenda-empty">' + I(failed ? 'alert' : 'leaf') + (failed ? 'Не удалось загрузить события.' : 'Сегодня пока нет событий.<br>Можно оставить место спонтанности.') + '</div>';
            return;
        }
        state.today.forEach(o => {
            const cat = category(o), s = new Date(o.start_at), f = new Date(o.finish_at),
                button = document.createElement('button');
            button.className = 'agenda-card' + (+new globalThis.Date(o.finish_at) < globalThis.Date.now() ? ' past' : '');
            button.innerHTML = '<span class="agenda-icon" style="color:' + cat.color + ';background:' + cat.background + '">' + I(cat.icon) + '</span><span class="agenda-copy"><b>' + E(o.title) + '</b><small>' + C.time(s) + ' — ' + C.time(f) + (+new globalThis.Date(o.start_at) <= globalThis.Date.now() && +new globalThis.Date(o.finish_at) > globalThis.Date.now() ? ' · сейчас' : '') + '</small></span>';
            button.onclick = () => D.details(o);
            container.append(button);
        });
    }

    async function loadSchedule() {
        $('#reload-schedule').disabled = true;
        const generation = ++state.generation;
        state.controller?.abort();
        state.controller = new AbortController();
        const signal = state.controller.signal;
        const weekView = state.page === 'schedule' && state.view === 'week', first = C.weekStart(state.anchor),
            today = C.dayStart(new Date());
        state.occurrences = [];
        drawEvents();
        $('#calendar-surface').setAttribute('aria-busy', String(weekView));
        try {
            const [weekResult, todayResult] = await Promise.all([weekView ? A.schedule(first, C.addDays(first, 7), signal) : Promise.resolve({occurrences: []}), A.schedule(today, C.addDays(today, 1), signal)]);
            if (generation !== state.generation) return;
            state.occurrences = weekResult.occurrences;
            state.today = todayResult.occurrences;
            setError('');
            document.body.classList.add('connected');
            drawEvents();
            renderToday();
            renderMini();
        } catch (error) {
            if (error.name === 'AbortError' || generation !== state.generation) return;
            state.today = [];
            setError(error.message);
            renderToday(true);
            document.body.classList.remove('connected');
        } finally {
            if (generation === state.generation) {
                $('#calendar-surface').setAttribute('aria-busy', 'false');
                $('#reload-schedule').disabled = false;
            }
        }
    }

    async function loadSeries(more = false) {
        const generation = ++state.listGeneration;
        if (!more) state.series = [];
        $('#load-more').hidden = true;
        if (!more) $('#events-list').innerHTML = '<div class="empty-state">' + I('book') + '<p>Открываем страницы…</p></div>';
        try {
            const rows = await A.list(state.series.length);
            if (generation !== state.listGeneration || state.page !== 'events') return;
            state.series.push(...rows);
            setError('');
            const target = $('#events-list');
            target.innerHTML = '';
            if (!state.series.length) {
                target.innerHTML = '<div class="empty-state">' + I('book') + '<h2>Новая глава</h2><p>Здесь появятся ваши события.<br>Начните с первого плана на день.</p></div>';
                return;
            }
            state.series.forEach(s => {
                const button = document.createElement('button');
                button.className = 'series-card';
                const cat = category(s), d = new Date(s.start_at);
                button.innerHTML = '<span class="agenda-icon" style="color:' + cat.color + ';background:' + cat.background + '">' + I(cat.icon) + '</span><span><strong>' + E(s.title) + '</strong><small>' + E(d.toLocaleDateString('ru-RU', {
                    day: 'numeric',
                    month: 'long',
                    year: 'numeric'
                })) + ' · ' + C.time(d) + (s.recurrence_rule ? ' · повторяется' : '') + '</small></span><span class="series-arrow">' + I('chevron-right') + '</span>';
                button.onclick = () => D.details({...s, event_series_id: s.id, original_start_at: s.start_at}, true);
                target.append(button);
            });
            $('#load-more').hidden = rows.length < 100;
        } catch (e) {
            if (generation !== state.listGeneration) return;
            setError(e.message);
            if (!more) $('#events-list').innerHTML = '<div class="empty-state">' + I('alert') + '<p>События пока недоступны.</p></div>';
        }
    }

    window.addEventListener('calendar-changed', e => {
        toast(e.detail);
        loadSchedule();
        if (state.page === 'events') loadSeries();
    });
    window.addEventListener('tasks-changed', e => {
        toast(e.detail);
        CompanionTasks.loadCalendar(C.weekStart(state.anchor), C.addDays(C.weekStart(state.anchor), 6), renderMini);
    });
    let lastDay = C.dateKey(new Date());
    setInterval(() => {
        drawNow();
        const today = C.dateKey(new Date());
        if (today !== lastDay) {
            lastDay = today;
            renderCalendar();
            loadSchedule();
        }
    }, 60000);
    renderToday();
    showPage(storage.get('currentPage', 'schedule'));
    if (state.page !== 'schedule') {
        renderCalendar();
        loadSchedule();
    }
})();
