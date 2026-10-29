(() => {
    const preview = CompanionAPI.preview;
    const sample = {
        id: 'local',
        kind: 'ollama',
        name: 'Локальная Ollama',
        base_url: 'http://127.0.0.1:11434',
        timeout: 60,
        connect_timeout: 10,
        has_api_key: false
    };

    async function request(path = '', method = 'GET', body) {
        if (preview) {
            if (method !== 'GET') throw new Error('Изменения и проверка доступны в запущенном приложении.');
            return path ? {...sample} : [{...sample}];
        }
        let response;
        try {
            response = await fetch('/api/llm/providers' + path, {
                method, cache: 'no-store',
                headers: {'Content-Type': 'application/json'},
                body: body === undefined ? undefined : JSON.stringify(body)
            });
        } catch {
            throw new Error('Нет связи с приложением. Повторите попытку позже.');
        }
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            const detail = payload.detail;
            const messages = {
                403: 'Настройки моделей доступны только с этого устройства.',
                404: 'Подключение не найдено. Обновите список.',
                409: 'Такой идентификатор уже занят или подключение используется.',
                422: 'Проверьте введённые данные подключения.',
                429: 'Провайдер ограничил число запросов. Попробуйте позже.',
                502: 'Не удалось связаться с провайдером. Проверьте адрес и ключ.',
                503: 'Провайдер сейчас недоступен.',
                504: 'Провайдер не ответил вовремя.'
            };
            // Do not show raw upstream messages: they can contain credentials or URLs.
            throw new Error(messages[response.status] || (typeof detail === 'object' && detail?.code ? 'Ошибка подключения: ' + detail.code : 'Не удалось выполнить действие.'));
        }
        return response.status === 204 ? null : response.json();
    }

    const path = id => '/' + encodeURIComponent(id);
    window.CompanionLLMAPI = {
        preview,
        list: () => request(),
        get: id => request(path(id)),
        create: data => request('', 'POST', data),
        update: (id, data) => request(path(id), 'PATCH', data),
        remove: id => request(path(id), 'DELETE'),
        check: id => request(path(id) + '/check', 'POST')
    };
})();
