-- Moldova uses the shared country registry; 0144 is reserved for rating clusters.
insert into ratings.countries (code, name_ru, name_en, is_imf)
values ('MD', 'Молдова', 'Moldova', true)
on conflict (code) do nothing;
