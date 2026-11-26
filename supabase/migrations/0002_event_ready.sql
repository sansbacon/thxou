-- Forward-only event-readiness update for databases where 0001_initial.sql
-- is already applied. This migration changes projections and authorization
-- checks only; it creates no records.

create or replace function public.get_contest_invitation(p_contest_id uuid) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object(
   'id',c.id,'title',c.title,'description',c.description,'deadline_at',c.deadline_at,
   'deadline_display',to_char(c.deadline_at at time zone c.creator_timezone,'FMMonth FMDD, YYYY at FMHH12:MI AM')||' '||c.creator_timezone,
   'creator',p.username,'creator_timezone',c.creator_timezone,'published_at',c.published_at,
   'is_creator',c.creator_id=auth.uid(),
   'can_edit',c.creator_id=auth.uid() and c.first_joined_at is null,
   'can_publish',c.creator_id=auth.uid() and c.published_at is null and c.first_joined_at is null
      and c.deadline_at>clock_timestamp() and (select count(*) from questions where contest_id=c.id) between 1 and 30,
   'can_view_leaderboard',c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid()),
   'can_submit',c.published_at is not null and c.deadline_at>clock_timestamp(),
   'results_visible',c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid()),
   'phase',case
     when c.published_at is null then 'draft'
     when c.deadline_at>clock_timestamp() then 'open'
     when not (c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid())) then 'closed'
     when (select count(*) from question_results r where r.contest_id=c.id)=(select count(*) from questions q where q.contest_id=c.id) then 'completed'
     else 'resolving'
   end,
   'questions',coalesce((select jsonb_agg(jsonb_build_object(
      'id',q.id,'text',q.text,
      'resolved',case when c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid())
                      then exists(select 1 from question_results r where r.question_id=q.id) else null end,
      'correct_answer',case when c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid())
                            then (select r.correct_answer from question_results r where r.question_id=q.id) else null end
   ) order by q.position) from questions q where q.contest_id=c.id),'[]'::jsonb),
   'version',(select b.version from ballots b where b.contest_id=c.id and b.user_id=auth.uid()),
   'answers',coalesce((select jsonb_object_agg(a.question_id::text,a.choice) from answers a where a.contest_id=c.id and a.user_id=auth.uid()),'{}'::jsonb)
 )
 from contests c join profiles p on p.user_id=c.creator_id
 where auth.uid() is not null and c.id=p_contest_id and (c.published_at is not null or c.creator_id=auth.uid());
$$;

create or replace function public.list_my_contests() returns setof jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object(
   'id',c.id,'title',c.title,
   'phase',case
     when c.published_at is null then 'draft'
     when c.deadline_at>clock_timestamp() then 'open'
     when (select count(*) from question_results r where r.contest_id=c.id) =
          (select count(*) from questions q where q.contest_id=c.id) then 'completed'
     else 'resolving'
   end,
   'deadline_at',c.deadline_at,
   'deadline_display',to_char(c.deadline_at at time zone c.creator_timezone,'FMMonth FMDD, YYYY at FMHH12:MI AM')||' '||c.creator_timezone)
 from contests c where c.creator_id=auth.uid() or exists(select 1 from ballots b where b.contest_id=c.id and b.user_id=auth.uid());
$$;

create or replace function public.get_leaderboard(p_contest_id uuid) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 with authorized as (
   select c.id,c.title,c.deadline_at,c.creator_timezone,c.published_at,c.creator_id
   from contests c
   where auth.uid() is not null and c.id=p_contest_id
     and (c.creator_id=auth.uid() or exists(select 1 from ballots mine where mine.contest_id=c.id and mine.user_id=auth.uid()))
 ), members as (
   select b.user_id from ballots b where b.contest_id=p_contest_id and exists(select 1 from authorized)
 ), scores as (
   select m.user_id,coalesce(sum(case when a.choice=r.correct_answer then 1 else 0 end),0)::int score
   from members m
   left join answers a on a.user_id=m.user_id and a.contest_id=p_contest_id
   left join question_results r on r.question_id=a.question_id
   group by m.user_id
 ), ranked as (
   select s.*,rank() over(order by score desc) rank from scores s
 )
 select jsonb_build_object(
   'id',p_contest_id,
   'title',(select title from authorized),
   'deadline_at',(select deadline_at from authorized),
   'deadline_display',(select to_char(deadline_at at time zone creator_timezone,'FMMonth FMDD, YYYY at FMHH12:MI AM')||' '||creator_timezone from authorized),
   'is_creator',(select creator_id=auth.uid() from authorized),
   'can_resolve',(select creator_id=auth.uid() and published_at is not null and deadline_at<=clock_timestamp()
                  and exists(select 1 from questions q where q.contest_id=p_contest_id and not exists(select 1 from question_results r where r.question_id=q.id)) from authorized),
   'standings',coalesce((select jsonb_agg(jsonb_build_object('username',p.username,'name',p.name,'score',r.score,'rank',r.rank) order by r.rank,p.username) from ranked r join profiles p on p.user_id=r.user_id),'[]'::jsonb),
   'question_count',(select count(*) from questions where contest_id=p_contest_id),
   'resolved_count',(select count(*) from question_results where contest_id=p_contest_id),
   'phase',case
     when (select published_at from authorized) is null then 'draft'
     when (select deadline_at from authorized)>clock_timestamp() then 'open'
     when (select count(*) from question_results where contest_id=p_contest_id)=(select count(*) from questions where contest_id=p_contest_id) then 'completed'
     else 'resolving'
   end,
   'questions',coalesce((select jsonb_agg(jsonb_build_object(
     'id',q.id,'text',q.text,'resolved',r.question_id is not null,'correct_answer',r.correct_answer
   ) order by q.position) from questions q left join question_results r on r.question_id=q.id where q.contest_id=p_contest_id),'[]'::jsonb),
   'as_of',clock_timestamp()
 )
 where exists(select 1 from authorized);
$$;

create or replace function public.resolve_question(p_contest_id uuid,p_question_id uuid,p_correct_answer boolean,p_confirmation boolean) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare c contests; existing boolean;
begin
 select * into c from contests where id=p_contest_id for update;
 if not p_confirmation or not found or c.creator_id<>auth.uid() or c.published_at is null or clock_timestamp()<c.deadline_at then
   raise exception 'resolution not authorized';
 end if;
 if not exists(select 1 from questions where id=p_question_id and contest_id=p_contest_id) then raise exception 'question not found'; end if;
 select correct_answer into existing from question_results where question_id=p_question_id;
 if found then
   if existing<>p_correct_answer then raise exception 'result is immutable'; end if;
   return;
 end if;
 insert into question_results(question_id,contest_id,correct_answer,resolved_by)
 values(p_question_id,p_contest_id,p_correct_answer,auth.uid())
 on conflict(question_id) do nothing;
end $$;

revoke execute on function public.get_contest_invitation(uuid),public.list_my_contests(),
 public.get_leaderboard(uuid),public.resolve_question(uuid,uuid,boolean,boolean) from public, anon;
grant execute on function public.get_contest_invitation(uuid),public.list_my_contests(),
 public.get_leaderboard(uuid),public.resolve_question(uuid,uuid,boolean,boolean) to authenticated;
