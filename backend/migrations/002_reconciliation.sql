--
-- 退款对账（refund reconciliation）
-- 与 SQLAlchemy ORM 定义保持一致；无在线迁移执行器，仅保留实际 DDL。
--

CREATE TABLE public.reconciliations (
    id integer NOT NULL,
    class_code character varying(50) NOT NULL,
    date_from character varying(10) NOT NULL,
    date_to character varying(10) NOT NULL,
    state character varying(20) NOT NULL,
    constraint_spec json,
    basis json,
    analysis json,
    correction json,
    created_by character varying(100),
    created character varying(40),
    analyzed_by character varying(100),
    analyzed_at character varying(40),
    applied_by character varying(100),
    applied_at character varying(40)
);

CREATE SEQUENCE public.reconciliations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reconciliations_id_seq OWNED BY public.reconciliations.id;

ALTER TABLE ONLY public.reconciliations ALTER COLUMN id SET DEFAULT nextval('public.reconciliations_id_seq'::regclass);

ALTER TABLE ONLY public.reconciliations
    ADD CONSTRAINT reconciliations_pkey PRIMARY KEY (id);
