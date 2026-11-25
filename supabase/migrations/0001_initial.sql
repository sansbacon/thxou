create extension if not exists pgcrypto;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete restrict,
  name text not null check (char_length(name) between 1 and 80),
  username text not null unique check (username ~ '^[a-z][a-z0-9_]{2,23}$'),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.contests (
  id uuid primary key default gen_random_uuid(), creator_id uuid not null references public.profiles(user_id) on delete restrict,
  title text not null check (char_length(title) between 1 and 120), description text check (description is null or char_length(description)<=1000),
  deadline_at timestamptz not null, creator_timezone text not null, published_at timestamptz, first_joined_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.questions (
  id uuid primary key default gen_random_uuid(), contest_id uuid not null references public.contests(id) on delete restrict,
  position int not null check(position > 0), text text not null check(char_length(text) between 1 and 300),
  unique(contest_id, position), unique(contest_id, id)
);
create table public.ballots (
  contest_id uuid not null references public.contests(id) on delete restrict, user_id uuid not null references public.profiles(user_id) on delete restrict,
  submitted_at timestamptz not null default now(), updated_at timestamptz not null default now(), version int not null default 1 check(version>0),
  primary key(contest_id,user_id)
);
create table public.answers (
  contest_id uuid not null, user_id uuid not null, question_id uuid not null, choice boolean not null,
  primary key(contest_id,user_id,question_id),
  foreign key(contest_id,user_id) references public.ballots(contest_id,user_id) on delete restrict,
  foreign key(contest_id,question_id) references public.questions(contest_id,id) on delete restrict
);
create table public.question_results (
  question_id uuid primary key, contest_id uuid not null, correct_answer boolean not null,
  resolved_by uuid not null references public.profiles(user_id) on delete restrict, resolved_at timestamptz not null default now(),
  foreign key(contest_id,question_id) references public.questions(contest_id,id) on delete restrict
);
create index contests_creator_created on public.contests(creator_id,created_at);
create index ballots_user_contest on public.ballots(user_id,contest_id);
create index questions_contest_position on public.questions(contest_id,position);
create index answers_contest_question on public.answers(contest_id,question_id);
create index question_results_contest on public.question_results(contest_id,question_id);

alter table public.profiles enable row level security;
alter table public.contests enable row level security;
alter table public.questions enable row level security;
alter table public.ballots enable row level security;
alter table public.answers enable row level security;
alter table public.question_results enable row level security;
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

create or replace function public.upsert_my_profile(p_name text,p_username text) returns public.profiles
language plpgsql security definer set search_path=public,pg_temp as $$
declare result public.profiles;
begin
 if auth.uid() is null then raise exception 'not authenticated'; end if;
 insert into profiles(user_id,name,username) values(auth.uid(),p_name,lower(p_username))
 on conflict(user_id) do update set name=excluded.name,username=excluded.username,updated_at=now() returning * into result;
 return result;
end $$;
create or replace function public.get_contest_invitation(p_contest_id uuid) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object('id',c.id,'title',c.title,'description',c.description,'deadline_at',c.deadline_at,'creator',p.username,
 'questions',coalesce((select jsonb_agg(jsonb_build_object('id',q.id,'text',q.text) order by q.position) from questions q where q.contest_id=c.id),'[]'::jsonb),
 'version',(select b.version from ballots b where b.contest_id=c.id and b.user_id=auth.uid()),
 'answers',coalesce((select jsonb_object_agg(a.question_id::text,a.choice) from answers a where a.contest_id=c.id and a.user_id=auth.uid()),'{}'::jsonb))
 from contests c join profiles p on p.user_id=c.creator_id where c.id=p_contest_id and c.published_at is not null;
$$;
create or replace function public.list_my_contests() returns setof jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object(
   'id',c.id,
   'title',c.title,
   'phase',case
     when c.published_at is null then 'draft'
     when c.deadline_at>clock_timestamp() then 'open'
     when (select count(*) from question_results r where r.contest_id=c.id) =
          (select count(*) from questions q where q.contest_id=c.id) then 'completed'
     else 'resolving'
   end)
 from contests c where c.creator_id=auth.uid() or exists(select 1 from ballots b where b.contest_id=c.id and b.user_id=auth.uid());
$$;
create or replace function public.get_leaderboard(p_contest_id uuid) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 with authorized as (
   select c.deadline_at,c.published_at
   from contests c
   where c.id=p_contest_id
     and (c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid()))
 ), members as (select b.user_id from ballots b where b.contest_id=p_contest_id and exists(select 1 from authorized)
 ), scores as (select m.user_id,coalesce(sum(case when a.choice=r.correct_answer then 1 else 0 end),0)::int score
 from members m left join answers a on a.user_id=m.user_id and a.contest_id=p_contest_id left join question_results r on r.question_id=a.question_id group by m.user_id),
 ranked as (select s.*,rank() over(order by score desc) rank from scores s)
 select jsonb_build_object('standings',coalesce((select jsonb_agg(jsonb_build_object('username',p.username,'name',p.name,'score',r.score,'rank',r.rank) order by r.rank,p.username) from ranked r join profiles p on p.user_id=r.user_id),'[]'::jsonb),
 'question_count',(select count(*) from questions where contest_id=p_contest_id),
 'resolved_count',(select count(*) from question_results where contest_id=p_contest_id),
 'phase',case
   when (select deadline_at from authorized)>clock_timestamp() then 'open'
   when (select count(*) from question_results where contest_id=p_contest_id)=(select count(*) from questions where contest_id=p_contest_id) then 'completed'
   else 'resolving'
 end,
 'as_of',clock_timestamp())
 where exists(select 1 from authorized);
$$;
create or replace function public.get_my_profile() returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object('name',p.name,'username',p.username)
 from profiles p where p.user_id=auth.uid();
$$;
grant execute on function public.upsert_my_profile(text,text),public.get_my_profile(),public.get_contest_invitation(uuid),public.list_my_contests(),public.get_leaderboard(uuid) to authenticated;

create or replace function public.create_draft(p_title text,p_description text,p_deadline_at timestamptz,p_creator_timezone text,p_questions text[]) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare cid uuid; i int; q text;
begin
 if auth.uid() is null or not exists(select 1 from profiles where user_id=auth.uid()) then raise exception 'profile required'; end if;
 if char_length(trim(p_title)) not between 1 and 120 or p_deadline_at is null or p_creator_timezone is null then raise exception 'invalid contest'; end if;
 if coalesce(array_length(p_questions,1),0) not between 1 and 30 then raise exception 'invalid question count'; end if;
 insert into contests(creator_id,title,description,deadline_at,creator_timezone) values(auth.uid(),p_title,p_description,p_deadline_at,p_creator_timezone) returning id into cid;
 i:=0; foreach q in array p_questions loop if nullif(trim(q),'') is not null then i:=i+1; insert into questions(contest_id,position,text) values(cid,i,trim(q)); end if; end loop;
 if i not between 1 and 30 then raise exception 'invalid question count'; end if;
 return jsonb_build_object('id',cid);
end $$;
create or replace function public.edit_draft(p_contest_id uuid,p_title text,p_description text,p_deadline_at timestamptz,p_creator_timezone text,p_questions text[]) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare c contests; i int:=0; q text;
begin
 select * into c from contests where id=p_contest_id for update;
 if not found or c.creator_id<>auth.uid() or c.first_joined_at is not null then raise exception 'cannot edit'; end if;
 if char_length(trim(p_title)) not between 1 and 120 or p_deadline_at is null or p_creator_timezone is null then raise exception 'invalid contest'; end if;
 delete from questions where contest_id=p_contest_id;
 foreach q in array p_questions loop
   if nullif(trim(q),'') is not null then
     i:=i+1;
     insert into questions(contest_id,position,text) values(p_contest_id,i,trim(q));
   end if;
 end loop;
 if i not between 1 and 30 then raise exception 'invalid question count'; end if;
 update contests set title=trim(p_title),description=nullif(trim(p_description),''),
   deadline_at=p_deadline_at,creator_timezone=p_creator_timezone,updated_at=now()
 where id=p_contest_id;
end $$;
create or replace function public.get_my_contest_for_edit(p_contest_id uuid) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object('id',c.id,'title',c.title,'description',c.description,'deadline_at',c.deadline_at,
 'deadline_local',to_char(c.deadline_at at time zone c.creator_timezone,'YYYY-MM-DD"T"HH24:MI'),
 'creator_timezone',c.creator_timezone,'published_at',c.published_at,
 'questions',coalesce((select jsonb_agg(jsonb_build_object('id',q.id,'text',q.text) order by q.position) from questions q where q.contest_id=c.id),'[]'::jsonb))
 from contests c where c.id=p_contest_id and c.creator_id=auth.uid() and c.first_joined_at is null;
$$;
create or replace function public.publish_contest(p_contest_id uuid) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare c contests;
begin
 select * into c from contests where id=p_contest_id for update;
 if not found or c.creator_id<>auth.uid() or c.first_joined_at is not null or c.deadline_at<=clock_timestamp()
   or (select count(*) from questions where contest_id=p_contest_id) not between 1 and 30 then raise exception 'cannot publish'; end if;
 update contests set published_at=coalesce(published_at,now()),updated_at=now() where id=p_contest_id;
end $$;
create or replace function public.submit_ballot(p_contest_id uuid,p_answers text[],p_expected_version int) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare item text; parts text[]; c contests; expected_count int; supplied_count int; existing_version int;
begin
 if auth.uid() is null or not exists(select 1 from profiles where user_id=auth.uid()) then raise exception 'profile required'; end if;
 select * into c from contests where id=p_contest_id for update;
 if not found or c.published_at is null or clock_timestamp()>=c.deadline_at then raise exception 'ballot closed'; end if;
 select count(*) into expected_count from questions where contest_id=p_contest_id;
 supplied_count:=coalesce(array_length(p_answers,1),0);
 if supplied_count<>expected_count then raise exception 'complete ballot required'; end if;
 select version into existing_version from ballots where contest_id=p_contest_id and user_id=auth.uid();
 if found and existing_version<>p_expected_version then raise exception 'stale ballot'; end if;
 if existing_version is null and (select count(*) from ballots where contest_id=p_contest_id)>=100 then raise exception 'contest full'; end if;
 insert into ballots(contest_id,user_id,version) values(p_contest_id,auth.uid(),1)
 on conflict(contest_id,user_id) do update set version=ballots.version+1,updated_at=now();
 delete from answers where contest_id=p_contest_id and user_id=auth.uid();
 foreach item in array p_answers loop
  parts:=string_to_array(item,':');
  if array_length(parts,1)<>2 or parts[2] not in ('true','false') then raise exception 'invalid answer'; end if;
  if not exists(select 1 from questions where contest_id=p_contest_id and id=parts[1]::uuid) then raise exception 'foreign answer'; end if;
  insert into answers(contest_id,user_id,question_id,choice) values(p_contest_id,auth.uid(),parts[1]::uuid,parts[2]::boolean);
 end loop;
 update contests set first_joined_at=coalesce(first_joined_at,now()) where id=p_contest_id;
end $$;
create or replace function public.resolve_question(p_contest_id uuid,p_question_id uuid,p_correct_answer boolean,p_confirmation boolean) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare c contests; existing boolean;
begin
 select * into c from contests where id=p_contest_id for update;
 if not p_confirmation or not found or c.creator_id<>auth.uid() or clock_timestamp()<c.deadline_at then raise exception 'resolution not authorized'; end if;
 if not exists(select 1 from questions where id=p_question_id and contest_id=p_contest_id) then raise exception 'question not found'; end if;
 select correct_answer into existing from question_results where question_id=p_question_id;
 if found then
   if existing<>p_correct_answer then raise exception 'result is immutable'; end if;
   return;
 end if;
 insert into question_results(question_id,contest_id,correct_answer,resolved_by) values(p_question_id,p_contest_id,p_correct_answer,auth.uid())
 on conflict(question_id) do nothing;
end $$;
grant execute on function public.create_draft(text,text,timestamptz,text,text[]),public.edit_draft(uuid,text,text,timestamptz,text,text[]),
 public.get_my_contest_for_edit(uuid),public.publish_contest(uuid),public.submit_ballot(uuid,text[],int),
 public.resolve_question(uuid,uuid,boolean,boolean) to authenticated;

revoke execute on all functions in schema public from public, anon;
