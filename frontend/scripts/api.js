(() => {
    const Date = CompanionTime.Date;
    const C = CompanionCalendar;
    const preview = location.protocol === 'file:' || new URLSearchParams(location.search).get('preview') === '1';

    class ApiError extends Error {
        constructor(message, status = 0, detail = '') {
            super(message);
            this.status = status;
            this.detail = detail;
        }
    }

    async function request(path, options = {}) {
        let response;
        try {
            response = await fetch('/api' + path, {
                ...options,
                headers: {'Content-Type': 'application/json', ...options.headers}
            });
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            throw new ApiError('Не удалось связаться с приложением. Проверьте, что оно запущено.');
        }
        if (!response.ok) {
            let payload;
            try {
                payload = await response.json();
            } catch {
                payload = {};
            }
            const detail = payload.detail;
            let message = {
                404: 'Событие не найдено. Возможно, оно уже удалено.',
                409: 'Изменение затрагивает существующие переносы или отмены.',
                422: 'Проверьте даты, название и параметры повторения.',
                503: 'Приложение занято. Попробуйте ещё раз через несколько секунд.'
            }[response.status] || 'Не удалось выполнить действие. Попробуйте ещё раз.';
            if (response.status === 422 && Array.isArray(detail)) {
                const names = {
                    title: 'название',
                    start_at: 'начало',
                    finish_at: 'окончание',
                    timezone: 'часовой пояс',
                    count: 'количество повторений',
                    until: 'окончание повторений'
                };
                const field = detail.map(e => names[e.loc?.at(-1)]).find(Boolean);
                if (field) message = 'Проверьте поле «' + field + '».';
            }
            throw new ApiError(message, response.status, typeof detail === 'string' ? detail : '');
        }
        return response.status === 204 ? null : response.json();
    }

    const demoSeries = [];
    const week = C.weekStart(new Date());

    function demo(day, hour, length, title, category = 'default', minute = 0) {
        const start = C.addDays(week, day);
        start.setHours(hour, minute, 0, 0);
        const end = new Date(+start + length * 36e5), id = 'preview-' + demoSeries.length;
        demoSeries.push({
            id,
            title,
            description: 'Небольшой план на день. Это пример события для знакомства с оформлением дневника.',
            start_at: start.toISOString(),
            finish_at: end.toISOString(),
            timezone: CompanionTime.zone,
            recurrence_rule_id: null,
            recurrence_rule: null,
            category
        });
    }

    for (let i = 0; i < 5; i++) demo(i, 9, 1.5, i === 0 ? 'Планирование недели' : 'Время для важного', 'work');
    demo(0, 12, 1, 'Обед и прогулка', 'rest');
    demo(0, 16, 1.5, 'Наброски персонажа', 'learning');
    demo(1, 11, 1, 'Обсудить идеи', 'default');
    demo(1, 11, 1.5, 'Заметки по проекту', 'learning', 30);
    demo(1, 15, 2, 'Работа над проектом', 'work');
    demo(2, 12, 1, 'Перерыв на обед', 'personal');
    demo(2, 16, 1, 'Почитать новую книгу', 'learning');
    demo(3, 11, 1.5, 'Дизайн приложения', 'learning');
    demo(3, 13, 1, 'Прогулка', 'rest');
    demo(3, 16, 1, 'Встреча с другом', 'personal');
    demo(3, 18, 1.5, 'Время для рисования', 'learning');
    demo(4, 12, 1, 'Подвести итоги', 'default');
    demo(4, 17, 2, 'Свободный вечер', 'personal');
    demo(5, 10, 1.5, 'Неспешное утро', 'rest');
    demo(5, 15, 3, 'Приключение начинается', 'personal');
    demo(6, 11, 1.5, 'Прогулка в парке', 'rest');
    demo(6, 17, 1, 'Планы на новую неделю', 'default');
    const asOccurrence = s => ({...s, event_series_id: s.id, original_start_at: s.start_at});
    const ensureLive = () => {
        if (preview) throw new ApiError('В предпросмотре изменения недоступны. Откройте интерфейс запущенного приложения.');
    };
    const occurrencePath = o => '/events/' + encodeURIComponent(o.event_series_id) + '/occurrences/' + encodeURIComponent(o.original_start_at);
    window.CompanionAPI = {
        preview, ApiError,
        schedule: async (a, b, signal) => preview ? {occurrences: demoSeries.filter(e => new Date(e.start_at) < b && new Date(e.finish_at) > a).map(asOccurrence)} : request('/schedule?' + new URLSearchParams({
            range_start: a.toISOString(),
            range_end: b.toISOString()
        }), {signal}),
        get: async id => preview ? demoSeries.find(e => e.id === id) : request('/events/' + encodeURIComponent(id)),
        list: async (offset = 0) => preview ? demoSeries.slice(offset, offset + 100) : request('/events?limit=100&offset=' + offset),
        create: body => {
            ensureLive();
            return request('/events', {method: 'POST', body: JSON.stringify(body)});
        },
        update: (id, body, reset = false) => {
            ensureLive();
            return request('/events/' + encodeURIComponent(id) + '?reset_exceptions=' + reset, {
                method: 'PATCH',
                body: JSON.stringify(body)
            });
        },
        remove: id => {
            ensureLive();
            return request('/events/' + encodeURIComponent(id), {method: 'DELETE'});
        },
        move: (o, body) => {
            ensureLive();
            return request(occurrencePath(o) + '/move', {method: 'POST', body: JSON.stringify(body)});
        },
        cancel: o => {
            ensureLive();
            return request(occurrencePath(o) + '/cancel', {method: 'POST'});
        },
        restore: o => {
            ensureLive();
            return request(occurrencePath(o) + '/restore', {method: 'POST'});
        }
    };
})();
