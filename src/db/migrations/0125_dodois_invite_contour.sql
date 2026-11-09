-- 0125_dodois_invite_contour.sql
--
-- Контур Dodo IS приглашения (D729). Страны лежат на двух контурах: международном
-- (`auth.dodois.com`) и СНГ (`auth.dodois.io`); какой из них у страны, публичные данные не
-- скажут, поэтому контур выбирает выдавший ссылку (по умолчанию — по стране), а страница
-- по ссылке ведёт вход на его сервер. Контур входа (`dodois.logins.contour`) уже есть и
-- заполняется из приглашения. Прежние ссылки — международные, как и было. Права таблицы
-- не меняются.
alter table dodois.invites
    add column contour text not null default 'intl' check (contour in ('intl', 'cis'));
comment on column dodois.invites.contour is
    'Контур Dodo IS, на который ведёт ссылка: intl (.com) или cis (.io).';
