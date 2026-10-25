(() => {
    async function request(path = '', method = 'GET', body, signal) {
        if (CompanionAPI.preview) {
            if (method === 'GET') return [];
            throw new Error('Изменение задач доступно в запущенном приложении.');
        }
        let response;
        try {
            response = await fetch('/api/tasks' + path, {
                method,
                signal,
                headers: {'Content-Type': 'application/json'},
                body: body === undefined ? undefined : JSON.stringify(body)
            });
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            throw new Error('Не удалось связаться с приложением. Проверьте подключение и повторите действие.');
        }
        if (!response.ok) {
            const errors = {
                404: 'Задача уже удалена или не найдена. Обновите доску.',
                409: 'Задачи изменились. Обновите доску и повторите действие.',
                422: 'Проверьте название, даты и параметры задачи.',
                503: 'База данных занята. Повторите действие.'
            };
            throw new Error(errors[response.status] || 'Не удалось сохранить или загрузить задачи. Повторите действие.');
        }
        return response.status === 204 ? null : response.json();
    }

    window.CompanionTasksAPI = {
        async list(filters = {}, signal) {
            const rows = [];
            for (let offset = 0; ; offset += 500) {
                const page = await request('?' + new URLSearchParams({
                    ...filters,
                    offset,
                    limit: 500
                }), 'GET', undefined, signal);
                rows.push(...page);
                if (page.length < 500) return rows;
            }
        },
        get: id => request('/' + encodeURIComponent(id)),
        create: body => request('', 'POST', body),
        update: (id, body) => request('/' + encodeURIComponent(id), 'PATCH', body),
        move: (id, status, position) => request('/' + encodeURIComponent(id) + '/move', 'PATCH', {status, position}),
        remove: id => request('/' + encodeURIComponent(id), 'DELETE')
    };
})();
