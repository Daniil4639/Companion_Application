(() => {
    const preview = CompanionAPI.preview;
    const example = {
        id: 'folliant', name: 'Folliant Local MCP', url: 'http://127.0.0.1:8181/mcp',
        is_internal: true, transport: 'streamable_http', connect_timeout: 10, operation_timeout: 30
    };

    async function request(path = '', method = 'GET', body) {
        if (preview) {
            if (method !== 'GET') throw new Error('Проверка и изменения доступны в запущенном приложении.');
            return path ? {...example} : [{...example}];
        }
        let response;
        try {
            response = await fetch('/api/mcp/servers' + path, {
                method, cache: 'no-store',
                headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined
            });
        } catch {
            throw new Error('Нет связи с приложением. Проверьте подключение и повторите попытку.');
        }
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            let message = {
                403: 'Системный плагин нельзя изменить. Настройки доступны только с этого устройства.',
                404: 'Плагин уже удалён. Обновите список.',
                409: 'Такой идентификатор уже занят или подключение сейчас закрывается.',
                422: 'Проверьте поля: название, идентификатор, адрес и время ожидания.',
                502: 'Не удалось подключиться. Проверьте адрес и убедитесь, что MCP-сервер запущен.',
                503: 'Приложение занято. Повторите попытку через несколько секунд.',
                504: 'Сервер не ответил вовремя. Настройки подключения сохранены.'
            }[response.status] || 'Не удалось выполнить действие. Повторите попытку.';
            if (response.status === 422 && Array.isArray(payload.detail)) {
                const names = {
                    id: 'Идентификатор',
                    name: 'Название',
                    url: 'Адрес сервера',
                    connect_timeout: 'Ожидание подключения',
                    operation_timeout: 'Ожидание ответа'
                };
                const field = payload.detail.map(e => names[e.loc?.at(-1)]).find(Boolean);
                if (field) message = 'Проверьте поле «' + field + '».';
            }
            throw new Error(message);
        }
        return response.status === 204 ? null : response.json();
    }

    const path = id => '/' + encodeURIComponent(id);
    window.CompanionMCPAPI = {
        preview, list: () => request(), get: id => request(path(id)),
        create: body => request('', 'POST', body), update: (id, body) => request(path(id), 'PATCH', body),
        remove: id => request(path(id), 'DELETE'), test: id => request(path(id) + '/test', 'POST')
    };
})();
