"""Рейтинги РС и РКО: разбор выгрузок, сопоставление, загрузка, сводка (спека «Рейтинги»).

Ярус между точками входа (`web`, `mcp`) и `db`: зовёт двери `src.db.ratings*` и
`src.domain`, сам SQL не пишет. Ядро с тестами до кода — `links`, `countries`,
`csvio`, `formats`, `sheet`, `snapshot`, `matching`, `periods`, `summary`.
"""
