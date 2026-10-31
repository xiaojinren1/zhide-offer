"""全部为虚构材料与 Mock 模型，不代表真实语义效果验收。"""
import copy
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from core.llm import LLMError, chat_json
from engine.models import Experience, ResumeProfile
from engine.tailoring import fact_catalog, plan_tailoring, review_tailoring, jd_units, has_evidence_anchor, markdown_excerpt_catalog

DEFAULT_MARKDOWN = '# 虚构同学\n使用 SQL 分析订单'


def excerpt_id(text, markdown=DEFAULT_MARKDOWN):
    return next((key for key, value in markdown_excerpt_catalog(markdown).items() if value == text), 'unknown-excerpt')


def profile():
    return ResumeProfile(name='虚构同学', user_confirmed=True, experiences=[
        Experience(name='校园产品', actions=['收集用户反馈', '绘制报名原型'], results=['输出需求文档'], skills=['原型设计']),
        Experience(name='数据练习', actions=['整理练习数据', '使用 SQL 分析订单'], results=['形成分析报告'], skills=['SQL'])],
        skills=['SQL'], education=['虚构大学 本科'])


def planned(quote='使用 SQL 分析', ids=None, priority='core'):
    return {'quote': quote, 'priority': priority, 'evidence_ids': ['e2.actions.2'] if ids is None else ids}


def audited(key='r1', quote='使用 SQL 分析订单', ids=None, markdown=DEFAULT_MARKDOWN):
    return {'id': key, 'excerpt_id': excerpt_id(quote, markdown) if quote else '', 'evidence_ids': ['e2.actions.2'] if ids is None else ids,
            'reason': '已确认的 SQL 订单分析行动体现岗位分析要求'}


class TailoringEngine(unittest.TestCase):
    def test_jd_units_preserve_all_clauses_and_deduplicate_without_silent_truncation(self):
        self.assertEqual(jd_units('核心要求：使用 SQL 分析，熟悉 Java；绘制原型。\n熟悉 Java'),
                         ['核心要求：使用 SQL 分析', '熟悉 Java', '绘制原型'])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            jd_units('；'.join(f'要求{i}' for i in range(81)))
        self.assertEqual(caught.exception.status_code, 422)

    def test_planner_cannot_omit_core_units_or_only_return_a_fragment(self):
        for rows in [[planned('绘制原型', ['e1.actions.2'], 'support')],
                     [planned('SQL'), planned('熟悉 Java', []), planned('绘制原型', [])]]:
            with patch('engine.tailoring.chat_json', return_value={'requirements': rows}), self.assertRaises(LLMError):
                plan_tailoring(profile(), '使用 SQL 分析；熟悉 Java；绘制原型', 4, deadline_at=time.monotonic()+60)

    def test_planning_covers_all_units_even_when_there_are_more_than_twenty(self):
        rows = [planned(f'职责{i}', [], 'support') for i in range(25)]
        with patch('engine.tailoring.chat_json', return_value={'requirements': rows}):
            plan, _, _ = plan_tailoring(profile(), '；'.join(row['quote'] for row in rows), 4, deadline_at=time.monotonic()+60)
        self.assertEqual(len(plan['requirements']), 25)

    def test_evidence_anchors_do_not_accept_name_or_partial_english_tokens(self):
        for quote, fact, expected in [('虚构同学', '使用 SQL 分析订单', False),
                                      ('NoSQL', 'SQL', False), ('SQL 分析', '使用 SQL 分析订单', True),
                                      ('负责整理反馈', '整理反馈', True), ('分析', '整理练习数据', False)]:
            self.assertEqual(has_evidence_anchor(quote, fact), expected)

    def test_name_excerpt_with_real_evidence_ids_is_unaddressed_not_success(self):
        plan, _, _ = self.plan()
        raw = {'items': [audited(quote='# 虚构同学', markdown='# 虚构同学')], 'unsupported_claims': []}
        with patch('engine.tailoring.chat_json', return_value=raw):
            report = review_tailoring(plan, '# 虚构同学', profile(), deadline_at=time.monotonic()+60)
        self.assertEqual(report['requirements'][0]['output_excerpt'], '')

    def test_excerpt_requires_active_fact_id_and_reason(self):
        plan, _, _ = self.plan()
        body = '使用 SQL 分析订单'
        for item in [audited(ids=[], markdown=body), audited(ids=['e1.actions.1'], markdown=body), audited(ids=['e2.actions.2']*2, markdown=body),
                     {**audited(markdown=body), 'reason': ''}, {**audited(markdown=body), 'evidence_ids': [{}]},
                     {'id': 'r1', 'excerpt_id': excerpt_id(body, body)}]:
            with patch('engine.tailoring.chat_json', return_value={'items': [item], 'unsupported_claims': []}), self.assertRaises(LLMError):
                review_tailoring(plan, '使用 SQL 分析订单', profile(), deadline_at=time.monotonic()+60)

    def plan(self, rows=None, max_n=4):
        rows = [planned()] if rows is None else rows
        jd = '；'.join(row.get('quote', '') for row in rows if isinstance(row, dict) and isinstance(row.get('quote'), str)) or '使用 SQL 分析'
        # 无效用例中“管理团队”必须仍是不属于 JD 的伪造引用。
        jd = jd.replace('管理团队', '使用 SQL 分析')
        with patch('engine.tailoring.chat_json', return_value={'requirements': rows}):
            return plan_tailoring(profile(), jd, max_n, deadline_at=time.monotonic()+100)

    def test_two_jds_select_different_experiences_and_reorder_facts(self):
        original = profile()
        before = original.to_dict()
        for quote, ids, first, action in [('使用 SQL 分析', ['e2.actions.2'], '数据练习', '使用 SQL 分析订单'),
                                         ('绘制报名原型', ['e1.actions.2'], '校园产品', '绘制报名原型')]:
            with patch('engine.tailoring.chat_json', return_value={'requirements': [planned(quote, ids)]}):
                plan, selected, dropped = plan_tailoring(original, quote, 1, deadline_at=time.monotonic()+100)
            self.assertEqual(selected[0].name, first)
            self.assertEqual(selected[0].actions[0], action)
            self.assertEqual(len(dropped), 1)
            self.assertEqual(plan['requirements'][0]['status'], 'supported')
        self.assertEqual(original.to_dict(), before)

    def test_gap_is_not_rewritten_as_skill(self):
        plan, _, _ = self.plan([planned('熟悉 Java', [])])
        self.assertEqual(plan['requirements'][0]['status'], 'gap')
        self.assertEqual(plan['requirements'][0]['active_evidence'], [])
        self.assertNotIn('raw_text', fact_catalog(profile()))

    def test_dropped_evidence_is_omitted_not_supported(self):
        plan, selected, _ = self.plan([planned(), planned('绘制报名原型', ['e1.actions.2'], 'support')], max_n=1)
        self.assertEqual(selected[0].name, '数据练习')
        self.assertEqual(plan['requirements'][1]['status'], 'omitted')
        self.assertEqual(plan['requirements'][1]['active_evidence'], [])

    def test_no_cap_keeps_all_experiences(self):
        self.assertEqual(len(self.plan(max_n=0)[1]), 2)

    def test_rejects_fabricated_requirement_evidence_duplicate_and_bad_structure(self):
        for rows in [[], [None], [planned('管理团队')], [planned(ids=['e9.actions.1'])],
                     [planned(ids=['e1.name.1'])], [planned(ids=['e2.actions.2']*2)],
                     [planned(priority='must')], [planned(), planned()],
                     [planned(ids=[{}])], [planned()]*21]:
            with self.subTest(rows=rows), self.assertRaises(LLMError):
                self.plan(rows)

    def test_priority_per_requirement_not_number_of_facts(self):
        rows = [planned('绘制报名原型', ['e1.actions.1', 'e1.actions.2', 'e1.results.1'], 'support'), planned()]
        self.assertEqual(self.plan(rows, max_n=1)[1][0].name, '数据练习')

    def test_education_and_global_skills_reconstruct_original_text(self):
        p = profile()
        p.experiences.append(Experience(kind='education', name='虚构学校', role='本科'))
        with patch('engine.tailoring.chat_json', return_value={'requirements': [planned('本科', ['e3.education.1', 'profile.education.1'])]}):
            plan, _, _ = plan_tailoring(p, '本科', 1, deadline_at=time.monotonic()+100)
        self.assertEqual(plan['requirements'][0]['evidence'][0]['text'], '虚构学校 本科')

    def test_review_returns_verbatim_excerpt_and_flags_unmet_focus(self):
        plan, _, _ = self.plan([planned(), planned('绘制报名原型', ['e1.actions.2'])])
        raw = {'items': [audited(), {'id': 'r2', 'excerpt_id': ''}], 'unsupported_claims': []}
        with patch('engine.tailoring.chat_json', return_value=raw):
            report = review_tailoring(plan, '# 虚构同学\n使用 SQL 分析订单', profile(), deadline_at=time.monotonic()+100)
        self.assertEqual(report['requirements'][1]['output_excerpt'], '')
        self.assertNotIn('active_evidence', report['requirements'][0])
        self.assertIn('不代表', report['review_note'])

    def test_catalog_preserves_multiline_markdown_and_unicode_without_rewriting(self):
        body = '# 虚构同学\r\n\r\n## 校园产品\r\n- 收集用户反馈\r\n- 绘制报名原型\r\n\r\n- 输出需求文档 📄\r\n- 收集用户反馈'
        catalog = markdown_excerpt_catalog(body)
        self.assertTrue(catalog)
        self.assertTrue(all(text in body for text in catalog.values()))
        self.assertIn('## 校园产品\r\n- 收集用户反馈\r\n- 绘制报名原型', catalog.values())
        self.assertIn('- 输出需求文档 📄', catalog.values())
        self.assertEqual(list(catalog.values()).count('- 收集用户反馈'), 1)

    def test_long_review_resolves_original_multiline_excerpt_without_model_copying(self):
        plan, _, _ = self.plan([planned(f'校园产品要求{i}', ['e1.actions.1', 'e1.actions.2', 'e1.results.1'])
                                for i in range(25)])
        body = '# 虚构同学\n\n## 校园产品\n- 收集用户反馈\n- 绘制报名原型\n- 输出需求文档'
        original = '## 校园产品\n- 收集用户反馈\n- 绘制报名原型\n- 输出需求文档'
        def audit_from_catalog(system, user, **kwargs):
            payload = json.loads(user)
            chosen = next(item['id'] for item in payload['excerpts'] if item['text'] == original)
            self.assertNotIn('markdown', payload)
            self.assertIn('excerpt_id', system)
            return {'items': [{'id': row['id'], 'excerpt_id': chosen,
                               'evidence_ids': ['e1.actions.1', 'e1.actions.2', 'e1.results.1'],
                               'reason': '已确认的反馈收集、原型及需求文档共同支持产品实践'}
                              for row in payload['plan']['requirements']], 'unsupported_claims': []}
        with patch('engine.tailoring.chat_json', side_effect=audit_from_catalog):
            report = review_tailoring(plan, body, profile(), deadline_at=time.monotonic()+100)
        self.assertEqual(len(report['requirements']), 25)
        self.assertTrue(all(row['output_excerpt'] == original for row in report['requirements']))
        self.assertTrue(all('excerpt_id' not in row for row in report['requirements']))

    def test_previous_body_excerpt_ids_cannot_be_reused_after_revision(self):
        plan, _, _ = self.plan()
        original = '# 虚构同学\n使用 SQL 分析订单'
        revised = original + '\n形成分析报告'
        self.assertTrue(set(markdown_excerpt_catalog(original)).isdisjoint(markdown_excerpt_catalog(revised)))
        for raw in [
            {'items': [audited(markdown=original)], 'unsupported_claims': []},
            {'items': [{'id': 'r1', 'excerpt_id': ''}], 'unsupported_claims': [
                {'excerpt_id': excerpt_id('使用 SQL 分析订单', original), 'reason': '旧正文编号'}]},
        ]:
            with self.subTest(raw=raw), patch('engine.tailoring.chat_json', return_value=raw), self.assertRaises(LLMError):
                review_tailoring(plan, revised, profile(), deadline_at=time.monotonic()+100)

    def test_review_rejects_fabricated_excerpt_missing_row_and_duplicate(self):
        plan, _, _ = self.plan()
        for items in [[], [{'id': 'r1', 'excerpt_id': 'unknown-excerpt'}], [{'id': 'r2', 'excerpt_id': ''}], [None],
                      [{'id': 'r1', 'excerpt_id': ''}, {'id': 'r1', 'excerpt_id': ''}],
                      [{'id': 'r1', 'quote': '旧协议原文'}]]:
            with patch('engine.tailoring.chat_json', return_value={'items': items, 'unsupported_claims': []}), self.assertRaises(LLMError):
                review_tailoring(plan, '# 测试', profile(), deadline_at=time.monotonic()+100)

    def test_review_gap_cannot_be_marked_addressed(self):
        plan, _, _ = self.plan([planned('熟悉 Java', [])])
        with patch('engine.tailoring.chat_json', return_value={'items': [audited(quote='熟悉 Java', markdown='熟悉 Java')], 'unsupported_claims': []}), self.assertRaises(LLMError):
            review_tailoring(plan, '熟悉 Java', profile(), deadline_at=time.monotonic()+100)

    def test_unsupported_claim_must_exist_in_markdown(self):
        plan, _, _ = self.plan()
        for quote in ['领导团队', '原句不存在']:
            with patch('engine.tailoring.chat_json', return_value={'items': [{'id': 'r1', 'excerpt_id': ''}],
                'unsupported_claims': [{'excerpt_id': excerpt_id(quote, '领导团队'), 'reason': '事实仅说明参与'}]}):
                if quote == '领导团队':
                    self.assertEqual(len(review_tailoring(plan, '领导团队', profile(), deadline_at=time.monotonic()+100)['unsupported_claims']), 1)
                else:
                    with self.assertRaises(LLMError):
                        review_tailoring(plan, '领导团队', profile(), deadline_at=time.monotonic()+100)

    def test_json_retry_shares_absolute_deadline(self):
        with patch('core.llm._time.monotonic', side_effect=[100, 110]), patch('core.llm._run_with_providers',
            side_effect=[{'content': 'bad json'}, {'content': '{}'}]) as run:
            self.assertEqual(chat_json('sys', 'usr', deadline_at=125), {})
        self.assertEqual([call.kwargs['deadline'] for call in run.call_args_list], [25, 15])

    def test_json_expired_never_calls_provider(self):
        with patch('core.llm._run_with_providers') as run, self.assertRaises(LLMError) as caught:
            chat_json('sys', 'usr', deadline_at=time.monotonic()-1)
        self.assertEqual(caught.exception.status_code, 504)
        run.assert_not_called()


class TailoringApi(unittest.TestCase):
    def setUp(self):
        from main import app
        from core.accounts import require_user
        from fastapi.testclient import TestClient
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[require_user] = lambda: {'id': 'mock-tailoring', 'username': 'mock_tailoring'}
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={'X-Requested-With': 'XMLHttpRequest'})
        for target in ('api.resume.is_configured', 'api.resume.events.emit'):
            patcher = patch(target, return_value=True)
            patcher.start(); self.addCleanup(patcher.stop)
        self.request = {'jd_text': '使用 SQL 分析；熟悉 Java', 'resume_profile': profile().to_dict(),
                        'use_examples': False, 'jd_keywords': ['SQL', 'Java', '伪造关键词']}
        self.model_plan = {'requirements': [planned(), planned('熟悉 Java', [])]}
        self.audit = {'items': [audited(), {'id': 'r2', 'excerpt_id': ''}], 'unsupported_claims': []}
        self.audit['items'][0] = audited()

    def test_full_flow_prompt_contains_verified_plan_and_only_supported_keywords(self):
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, self.audit]) as stages, patch('api.resume.chat_with_tools',
            return_value={'content': '# 虚构同学\n使用 SQL 分析订单', 'rounds': 1, 'tool_calls': []}) as writer:
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['tailoring']['requirements'][1]['status'], 'gap')
        payload = json.loads(writer.call_args.args[1].split('输入：')[1].split('\n\n')[0])
        self.assertEqual(payload['experiences'][0]['name'], '数据练习')
        self.assertEqual(payload['jd_keywords'], ['SQL'])
        self.assertIn('不补造', writer.call_args.args[0])
        self.assertEqual(stages.call_count, 2)
        self.assertLessEqual(writer.call_args.kwargs['flow_deadline'], 150)
        self.assertLess(stages.call_args_list[0].kwargs['deadline_at'], stages.call_args_list[1].kwargs['deadline_at'])
        self.assertLessEqual(writer.call_args.kwargs['flow_deadline'], 125)

    def test_expired_after_planning_stops_before_writer(self):
        with patch('api.resume.time') as clock, patch('engine.tailoring.chat_json',
            return_value=self.model_plan), patch('api.resume.chat_with_tools') as writer:
            clock.monotonic.side_effect = [0, 0, 0, 0, 151]
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 504)
        writer.assert_not_called()

    def test_planning_failure_never_falls_back_to_polishing(self):
        with patch('engine.tailoring.chat_json', return_value={'requirements': []}), patch('api.resume.chat_with_tools') as writer:
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('markdown', response.json())
        writer.assert_not_called()

    def test_invalid_audit_not_silently_delivered(self):
        broken = copy.deepcopy(self.audit); broken['items'][0]['excerpt_id'] = 'unknown-excerpt'
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, broken]), patch('api.resume.chat_with_tools',
            return_value={'content': '# 普通润色', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('markdown', response.json())

    def test_generic_draft_is_explicitly_unaddressed(self):
        audit = copy.deepcopy(self.audit); audit['items'][0]['excerpt_id'] = ''
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, audit, {'markdown': '# 虚构同学\n仍未体现'}, audit]), patch('api.resume.chat_with_tools',
            return_value={'content': '# 虚构同学\n认真积极', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tailoring']['requirements'][0]['output_excerpt'], '')
        self.assertEqual(response.json()['tailoring']['revision_count'], 1)

    def test_zero_budget_never_calls_models(self):
        with patch.dict('os.environ', {'JOBAGENT_FLOW_DEADLINE': '0'}), patch('engine.tailoring.chat_json') as model:
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 504)
        model.assert_not_called()

    def test_repair_once_and_recheck_final_body(self):
        first = copy.deepcopy(self.audit); first['items'][0]['excerpt_id'] = ''
        final = '# 虚构同学\n使用 SQL 分析订单'
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, first, {'markdown': final}, self.audit]) as stages, patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学\n积极认真', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['markdown'], final)
        self.assertEqual(response.json()['tailoring']['revision_count'], 1)
        self.assertEqual(stages.call_count, 4)
        payload = json.loads(stages.call_args_list[2].args[1])
        self.assertIn('review', payload)
        self.assertEqual(payload['plan']['requirements'][1]['status'], 'gap')
        self.assertTrue(all(call.kwargs['deadline_at'] <= stages.call_args.kwargs['deadline_at'] for call in stages.call_args_list))

    def test_unsupported_claims_trigger_repair_even_if_focus_was_addressed(self):
        first = copy.deepcopy(self.audit)
        final = '# 虚构同学\n使用 SQL 分析订单'
        first['items'][0] = audited(markdown=final+'\n领导团队')
        first['unsupported_claims'] = [{'excerpt_id': excerpt_id('领导团队', final+'\n领导团队'), 'reason': '事实仅说明分析订单'}]
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, first, {'markdown': final}, self.audit]), patch('api.resume.chat_with_tools', return_value={'content': final+'\n领导团队', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('领导团队', response.json()['markdown'])
        self.assertEqual(response.json()['tailoring']['unsupported_claims'], [])

    def test_invalid_or_failed_repair_never_returns_first_draft_as_success(self):
        first = copy.deepcopy(self.audit); first['items'][0]['excerpt_id'] = ''
        for result in [{'markdown': '稍后再修订'}, {}, LLMError('repair timeout', status_code=504)]:
            with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, first, result]), patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学', 'rounds': 1}):
                response = self.client.post('/api/resume/generate', json=self.request)
            self.assertIn(response.status_code, [502, 504])
            self.assertNotIn('markdown', response.json())

    def test_final_review_failure_does_not_deliver_unreviewed_repair(self):
        first = copy.deepcopy(self.audit); first['items'][0]['excerpt_id'] = ''
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, first, {'markdown': '# 虚构同学'}, LLMError('audit timeout', status_code=504)]), patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 504)
        self.assertNotIn('markdown', response.json())

    def test_gap_only_does_not_trigger_fabricating_repair(self):
        request = {**self.request, 'jd_text': '熟悉 Java'}
        plan = {'requirements': [planned('熟悉 Java', [])]}
        audit = {'items': [{'id': 'r1', 'excerpt_id': ''}], 'unsupported_claims': []}
        with patch('engine.tailoring.chat_json', side_effect=[plan, audit]) as stages, patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学\n使用 SQL 分析订单', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['tailoring']['revision_count'], 0)
        self.assertEqual(stages.call_count, 2)

    def test_budget_expired_during_repair_stops_before_final_review(self):
        first = {'requirements': [{'status': 'supported', 'output_excerpt': ''}], 'unsupported_claims': []}
        with patch('api.resume.time') as clock, patch('api.resume.plan_tailoring', return_value=({'requirements': []}, [], [])), patch('api.resume.review_tailoring', return_value=first) as review, patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学'}):
            clock.monotonic.return_value = 0
            def expire(*args, **kwargs):
                clock.monotonic.return_value = 151
                return '# 虚构同学'
            with patch('api.resume.repair_tailoring', side_effect=expire):
                response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(review.call_count, 1)
        self.assertNotIn('markdown', response.json())

    def test_final_numbers_checked_again_after_revision(self):
        first = copy.deepcopy(self.audit); first['items'][0]['excerpt_id'] = ''
        final = '# 虚构同学\n使用 SQL 分析订单，提升 98765%'
        final_audit = {'items': [audited(quote='使用 SQL 分析订单，提升 98765%', markdown=final), {'id': 'r2', 'excerpt_id': ''}], 'unsupported_claims': []}
        with patch('engine.tailoring.chat_json', side_effect=[self.model_plan, first, {'markdown': final}, final_audit]), patch('api.resume.chat_with_tools', return_value={'content': '# 虚构同学', 'rounds': 1}):
            response = self.client.post('/api/resume/generate', json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['traceability_passed'])
        self.assertTrue(response.json()['untraceable'])


if __name__ == '__main__':
    unittest.main()
