/* CalendarDate stores wall-clock components in UTC slots, independent of OS DST.
   Only API boundaries convert these components to real instants in the profile zone. */
(() => {
    const NativeDate = globalThis.Date;
    let zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    let formatter;
    const setZone = value => {
        formatter = new Intl.DateTimeFormat('en-CA', {
            timeZone: value,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hourCycle: 'h23'
        });
        zone = value;
    };
    setZone(zone);

    function wallStamp(instant) {
        const p = Object.fromEntries(formatter.formatToParts(new NativeDate(instant)).map(x => [x.type, x.value]));
        return NativeDate.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) + ((instant % 1000) + 1000) % 1000;
    }

    function resolve(stamp, strict = false) {
        const offsets = new Set();
        for (let h = -36; h <= 36; h += 6) {
            const t = stamp + h * 36e5;
            offsets.add(wallStamp(t) - t);
        }
        const candidates = [...offsets].map(offset => stamp - offset);
        const exact = candidates.filter(t => wallStamp(t) === stamp).sort((a, b) => a - b);
        if (exact.length) return exact[0]; // Earlier occurrence during an autumn overlap.
        if (strict) throw new Error('Это местное время не существует из-за перевода часов. Выберите другое время.');
        const forward = candidates.filter(t => wallStamp(t) > stamp).sort((a, b) => wallStamp(a) - wallStamp(b));
        if (forward.length) return forward[0]; // Calendar day boundary inside a DST gap.
        throw new Error('Не удалось преобразовать время выбранного пояса.');
    }

    class CalendarDate extends NativeDate {
        constructor(...args) {
            if (!args.length) super(wallStamp(NativeDate.now()));
            else if (args.length > 1) super(NativeDate.UTC(...args));
            else if (typeof args[0] === 'string') {
                const value = args[0];
                if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) super(wallStamp(+new NativeDate(value)));
                else super(value.length === 10 ? value + 'T00:00:00Z' : value + 'Z');
            } else if (args[0] instanceof NativeDate && !(args[0] instanceof CalendarDate)) super(wallStamp(+args[0]));
            else super(+args[0]);
        }

        getFullYear() {
            return this.getUTCFullYear();
        }

        getMonth() {
            return this.getUTCMonth();
        }

        getDate() {
            return this.getUTCDate();
        }

        getDay() {
            return this.getUTCDay();
        }

        getHours() {
            return this.getUTCHours();
        }

        getMinutes() {
            return this.getUTCMinutes();
        }

        getSeconds() {
            return this.getUTCSeconds();
        }

        setHours(...a) {
            return this.setUTCHours(...a);
        }

        setMinutes(...a) {
            return this.setUTCMinutes(...a);
        }

        setDate(...a) {
            return this.setUTCDate(...a);
        }

        toLocaleDateString(locale, options = {}) {
            return super.toLocaleDateString(locale, {...options, timeZone: 'UTC'});
        }

        toISOString() {
            return new NativeDate(resolve(+this)).toISOString();
        }
    }

    window.CompanionTime = {
        Date: CalendarDate, setZone, get zone() {
            return zone;
        },
        systemZone: () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        validateWall: date => resolve(+date, true)
    };
})();
