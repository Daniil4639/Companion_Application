(() => {
    const paths = {
        chat: '<path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 3-2Z"/><path d="M7 9h10M7 13h6"/>',
        user: '<circle cx="12" cy="8" r="4" fill="currentColor" stroke="none"/><path d="M4 21v-2a8 8 0 0 1 16 0v2Z" fill="currentColor" stroke="none"/>',
        calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 11h16m-11 4h2m3 0h2m-7 3h2"/>',
        list: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
        check: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/>',
        settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
        'panel-left': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m7-12-3 4 3 4"/>',
        'panel-right': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16m-7-12 3 4-3 4"/>',
        'chevron-left': '<path d="m14 6-6 6 6 6"/>',
        'chevron-right': '<path d="m10 6 6 6-6 6"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        close: '<path d="m6 6 12 12M6 18 18 6"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
        moon: '<path d="M20 15A8 8 0 0 1 9 4a8 8 0 1 0 11 11Z"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        repeat: '<path d="m17 2 4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4m14-1v2a3 3 0 0 1-3 3H3"/>',
        refresh: '<path d="M20 10a8 8 0 0 0-14-3L3 10m0-6v6h6"/><path d="M4 14a8 8 0 0 0 14 3l3-3m0 6v-6h-6"/>',
        arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        mouse: '<rect x="7" y="2" width="10" height="20" rx="5"/><path d="M12 6v4"/>',
        leaf: '<path d="M20 3C8 1 1 10 6 17s16 0 14-14Z"/><path d="M3 21 16 8m-5 5v-4m0 4h5"/>',
        book: '<path d="M12 5C8 2 4 3 3 4v16c4-2 6-1 9 1m0-16c4-3 8-2 9-1v16c-4-2-6-1-9 1V5"/>',
        flag: '<path d="M5 21V3m0 1c5-4 9 4 15 0v10c-6 4-10-4-15 0"/>',
        spark: '<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5Z"/>',
        alert: '<path d="M10 4a2 2 0 0 1 4 0l8 14a2 2 0 0 1-2 3H4a2 2 0 0 1-2-3Z"/><path d="M12 9v4m0 4h.01"/>',
        edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 15Z"/>',
        trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
        pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
        compass: '<circle cx="12" cy="12" r="8"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2m-7 5 4-2-2 4-4 2Z"/>',
        briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12c6 4 12 4 18 0M10 14h4"/>',
        game: '<path d="M7 7h10c4 0 6 12 3 13-2 1-4-4-5-4H9c-1 0-3 5-5 4C1 19 3 7 7 7Z"/><path d="M6 10v5m-2-2h4m7-2h.01m3 3h.01"/>',
        heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0l-1 1-1-1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
        branch: '<path d="M12 23V5m0 13c-7 0-9-4-8-8 5 0 8 3 8 8Zm0-4c7 0 9-4 8-8-5 0-8 3-8 8Zm0-6C8 5 9 2 12 1c3 1 4 4 0 7Z"/>'
    };
    const icon = name => '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + (paths[name] || paths.calendar) + '</svg>';
    window.CompanionIcons = {
        icon, mount: (root = document) => root.querySelectorAll('[data-icon]').forEach(el => {
            el.innerHTML = icon(el.dataset.icon);
        })
    };
    // Stable API keys; unknown/missing categories retain the default appearance.
    window.CompanionCategories = Object.freeze({
        default: {label: 'По умолчанию', icon: 'calendar', color: '#806E58', background: '#E9DDC6'},
        work: {label: 'Работа', icon: 'briefcase', color: '#A85B32', background: '#EDD3BD'},
        entertainment: {label: 'Развлечения', icon: 'game', color: '#9A7837', background: '#EEE0B8'},
        learning: {label: 'Обучение', icon: 'book', color: '#627B86', background: '#DCE5E3'},
        health: {label: 'Здоровье', icon: 'heart', color: '#A06462', background: '#EBD7D0'},
        personal: {label: 'Личное', icon: 'pin', color: '#84718D', background: '#E4DBE4'},
        rest: {label: 'Отдых', icon: 'leaf', color: '#78836B', background: '#DFE4D0'}
    });
})();
