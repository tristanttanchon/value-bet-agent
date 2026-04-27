-- Migration : table `fun_predictions`
-- À appliquer dans Supabase (SQL Editor) une seule fois.
--
-- Stocke les pronos fun générés à 11h, résolus le lendemain 18h
-- par fun_resolver.py.

create table if not exists public.fun_predictions (
    id                              bigserial primary key,
    date                            date      not null,
    competition                     text,
    kickoff                         text,
    match                           text      not null,
    home_team                       text,
    away_team                       text,
    fixture_id                      bigint,    -- ID API-Football pour la résolution
    -- Prédictions
    predicted_score                 text,      -- "2-1"
    predicted_scorers               jsonb,     -- [{"name":"Salah","team":"Liverpool"}, ...]
    predicted_first_scorer_team     text,      -- "home" | "away"
    predicted_first_scorer_pct      integer,
    bonus_scenario                  text,
    -- Résolution
    status                          text      not null default 'PENDING',  -- PENDING / RESOLVED
    actual_score                    text,
    actual_scorers                  jsonb,
    actual_first_scorer_team        text,
    score_correct                   boolean,
    scorers_hit_count               integer,
    scorers_predicted_count         integer,
    first_scorer_correct            boolean,
    -- Meta
    resolved_at                     timestamptz,
    created_at                      timestamptz not null default now()
);

-- Index pour la requête principale du resolver (status + date)
create index if not exists fun_predictions_status_date_idx
    on public.fun_predictions (status, date);

create index if not exists fun_predictions_date_idx
    on public.fun_predictions (date);
