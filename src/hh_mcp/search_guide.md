# hh.ru search: how to build the `text` argument

Read this before calling the `search` tool. Everything you put in `text` is sent to hh.ru as a search query, so the
operators below work exactly as they do in the hh.ru search box.

## What this server already filters out

Every `search` call runs with these filters, and you cannot change them:

| Filter                                             | What it means                                        |
|----------------------------------------------------|------------------------------------------------------|
| `salary_frequency=TWICE_PER_MONTH`                 | the salary is published and paid twice a month       |
| `employment_form=FULL`                             | full-time employment                                 |
| `experience=between1And3, between3And6, moreThan6` | at least one year of experience                      |
| `label=not_from_agency`                            | the employer is not an agency                        |
| `label=accept_labor_contract`                      | the employer signs a labour contract                 |
| `work_format=REMOTE, ON_SITE, HYBRID`              | remote, on-site and hybrid are all allowed           |
| `search_field=name, company_name, description`     | title, company name and description are all searched |

Never repeat these in `text` — it only narrows your own query. A vacancy with less than a year of experience, without a
published salary or from an agency is never returned, however good the query is. So when `search` returns nothing, the
filters are not what failed: widen the query first.

## Plain search, without operators

A query with no operators matches vacancies containing **at least one** of the words, anywhere in the title, the company
name or the description:

- words in any order and any case;
- any inflected form (`бухгалтер` also finds `бухгалтеров`, `бухгалтера`);
- synonyms (`менеджер проектов` also finds `Project Manager` and `проджект`).

Start with plain search to see how much the market offers, then tighten it with operators.

## Operators

| Operator    | Meaning                                               | Example                                               |
|-------------|-------------------------------------------------------|-------------------------------------------------------|
| `!слово`    | that exact word form only, no other inflections       | `!менеджер`                                           |
| `"фраза"`   | exact phrase, nothing inserted inside it              | `"главный бухгалтер"`                                 |
| `!"фраза"`  | exact phrase, and in that exact form                  | `!"инженер-конструктор"`                              |
| `"фраза"~N` | up to N words allowed between the words of the phrase | `"школа танцев"~5`                                    |
| `A AND B`   | both required, in any order and any form              | `маркетолог AND аналитик`                             |
| `A OR B`    | either one is enough                                  | `дизайнер OR иллюстратор`                             |
| `NOT слово` | exclude                                               | `программист NOT стажёр`                              |
| `слово*`    | prefix wildcard                                       | `менедж*`, `гео*`                                     |
| `( ... )`   | group conditions                                      | `(дизайнер OR иллюстратор) AND (удалённо OR фриланс)` |

`AND` also joins phrases and groups: `"email маркетолог" AND Unisender`.

## Search inside one field

| Operator        | Field                             |
|-----------------|-----------------------------------|
| `NAME:`         | vacancy title                     |
| `COMPANY_NAME:` | employer name                     |
| `DESCRIPTION:`  | vacancy description               |
| `!ID`           | vacancy ID — the `!` is required  |
| `!COMPANY_ID`   | employer ID — the `!` is required |

The colon is mandatory. The operator name itself is case-insensitive.

```
NAME:инженер
COMPANY_NAME:Сбер
DESCRIPTION:"коммерческая недвижимость"
!ID:38185674
```

## Recipes

- Several titles in one search:
  `("менеджер по продажам" OR "торговый представитель") AND Москва`
- One exact title and nothing like it: `NAME:"продуктовый редактор"`
- Hide what you do not want: `NOT "холодные продажи"`, `NOT junior`, `NOT 2/2`
- Required skills and stack: `"email маркетолог" AND Unisender`, `Python AND Kafka`
- Everything else — city, district, schedule, perks, format — is a plain word:
  `Москва`, `Химки`, `ДМС`, `гибрид`, `удалённо`, `2/2`

## Do not overconstrain

The more conditions you combine, the fewer vacancies come back. Keep only what the user actually asked for, and when a
search comes back empty, drop conditions one at a time:

1. remove `NOT`, quotes and `NAME:` — these are the strictest;
2. replace a wildcard with a whole word;
3. remove an `AND` group, keeping the most important words.

## Workflow

1. Read this resource.
2. Compose `text`: plain words plus at most the operators the request needs.
3. `search(text=..., page=0)` — it returns IDs only, about 20 per page.
4. Read the promising ones with `vacancy(id)`; read an employer with `company(id)`.
5. For more results, `search(text=..., page=1)` and onwards.

Source: <https://hh.ru/blog/lajfhaki-hh-bystryj-poisk-vakansij>
Markdown guide: filters, operators, field prefixes, recipes, workflow.