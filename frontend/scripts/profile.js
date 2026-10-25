(() => {
    const T = CompanionTime;
    const preview = location.protocol === 'file:' || new URLSearchParams(location.search).get('preview') === '1';

    async function request(method, body) {
        const response = await fetch('/user', {
            method,
            headers: {'Content-Type': 'application/json'},
            body: body ? JSON.stringify(body) : undefined,
            cache: 'no-store'
        });
        if (!response.ok) {
            const error = new Error(response.status === 409 ? 'Профиль уже создан. Обновите страницу.' : response.status === 422 ? 'Проверьте имя и часовой пояс (например, Europe/Moscow).' : 'Не удалось загрузить или сохранить профиль. Повторите попытку.');
            error.status = response.status;
            throw error;
        }
        return response.json();
    }

    const profile = {preview, user: null, request};
    profile.ready = (async () => {
        if (document.body.dataset.onboarding === 'true' || preview) return;
        try {
            profile.user = await request('GET');
            T.setZone(profile.user.timezone_mode === 'system' ? T.systemZone() : profile.user.timezone);
        } catch (error) {
            if (error.status === 404) {
                location.replace('/welcome');
                return;
            }
            throw error;
        }
    })();
    // Attach immediately; app presents the error instead of silently using another zone.
    profile.ready.catch(() => {
    });
    window.CompanionProfile = profile;
    // Re-read device settings when returning to the app after an OS timezone change.
    window.addEventListener('focus', () => {
        if (profile.user?.timezone_mode === 'system' && T.systemZone() !== T.zone) location.reload();
    });

    function mount() {
        const form = document.querySelector('#profile-form');
        if (!form) return;
        const onboarding = document.body.dataset.onboarding === 'true';
        const user = profile.user || {
            username: '',
            display_name: '',
            timezone: T.systemZone(),
            timezone_mode: 'system',
            locale: 'ru-RU'
        };
        for (const key of ['username', 'display_name', 'timezone', 'timezone_mode', 'locale']) form.elements[key].value = user[key] || '';
        let manual = user.timezone;
        const zoneField = form.elements.timezone;

        function syncMode() {
            const system = form.elements.timezone_mode.value === 'system';
            zoneField.disabled = system;
            zoneField.value = system ? T.systemZone() : manual;
        }

        form.elements.timezone_mode.onchange = syncMode;
        zoneField.oninput = () => manual = zoneField.value;
        syncMode();
        const list = document.querySelector('#timezone-options');
        const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['Europe/Moscow', 'Europe/London', 'America/New_York', 'Asia/Tokyo'];
        for (const name of new Set(['UTC', T.systemZone(), user.timezone, ...zones])) {
            const option = document.createElement('option');
            option.value = name;
            list.append(option);
        }
        if (preview) {
            form.querySelector('[type=submit]').disabled = true;
            form.querySelector('.profile-message').textContent = 'Сохранение профиля доступно в запущенном приложении.';
        }
        form.onsubmit = async event => {
            event.preventDefault();
            const message = form.querySelector('.profile-message'), button = form.querySelector('[type=submit]');
            message.textContent = '';
            button.disabled = true;
            try {
                const payload = {
                    username: form.elements.username.value.trim(),
                    display_name: form.elements.display_name.value.trim() || null,
                    timezone_mode: form.elements.timezone_mode.value,
                    timezone: zoneField.value.trim(),
                    locale: 'ru-RU'
                };
                if (!payload.username) throw new Error('Введите системное имя.');
                try {
                    new Intl.DateTimeFormat('ru', {timeZone: payload.timezone});
                } catch {
                    throw new Error('Выберите существующий часовой пояс IANA.');
                }
                await request(onboarding ? 'POST' : 'PATCH', payload);
                location.replace('/');
            } catch (error) {
                message.textContent = error.message;
                button.disabled = false;
            }
        };
    }

    profile.ready.then(mount).catch(() => {
    });
})();
