# coding=utf-8

from __future__ import division
import webapp2
import os
import math
import json
import datetime, time
import logging

from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api import search
from google.appengine.api.search import SortOptions, SortExpression
from google.appengine.api import users

from models import Link, Tag, LinkTag

		
def show_index(request, *args, **kwargs):
	return _get_list_and_render({'page': request.get('page')}, 'свежие поступления', 'index')

	
def show_list(request, *args, **kwargs):
	params = {}
	if kwargs.has_key('year'):
		params['year'] = int(kwargs['year'])
	if kwargs.has_key('month'):
		params['month'] = int(kwargs['month'])
	if kwargs.has_key('day'):
		params['day'] = int(kwargs['day'])
		
	params['page'] = request.get('page')
	
	return _get_list_and_render(params, 'список ссылок, добавленных в определенную дату')
	
	
def show_list_by_tag(request, *args, **kwargs):
	tag = Tag.gql('where name=:1',kwargs['tag'].decode('utf-8')).get()
	if tag == None:
		return _404()
	
	params = {}
	params['page'] = request.get('page')
	params['tag'] = tag
	return _get_list_and_render(params, 'список ссылок по тэгу')
	
def show_tags_list(request, *args, **kwargs):
	params = {}
	tags = Tag.all().order('name').fetch(1000)
	for tag in tags:
		tag.num_links = LinkTag.all().filter('tag = ', tag).filter('is_actual = ', True).filter('owner = ', users.get_current_user().user_id()).count()

	min_count = 1
	max_count = 1
	min_size = 10
	max_size = 20
	for tag in tags:
		if min_count > tag.num_links:
			min_count = tag.num_links 
		if max_count < tag.num_links:
			max_count = tag.num_links
			
	for tag in tags:
		tag.size = _get_size(min_size, max_size, tag.num_links-(min_count-1), max_count+1)

	params['tags'] = tags
	params['page_title'] = 'список тэгов'
	params['menu_items'] = get_menu_items()
	params['user'] = users.get_current_user().nickname()
	
	return _render_to_response(params, 'tags');

def _get_size(a,b,i,x):
	return int(math.log(i)*((b-a)/math.log(x))+a)	
	
def show_list_not_actual(request, *args, **kwargs):
	return _get_list_and_render({'not_actual': 1, 'page': request.get('page')}, 'уже не актуальные ссылки')
		
	
def save_item(request, *args, **kwargs):
	result = {}
	logging.info('item_id: %s', request.get('item_id'))
	if request.get('item_id'):
		link = Link.get(request.get('item_id'))
	else:
		link = Link()
		link.created = datetime.datetime.now()
		link.created_day = datetime.date.today().day
		link.created_month = datetime.date.today().month
		link.created_year = datetime.date.today().year
		link.owner = users.get_current_user().user_id()

	link.link = request.get('link')
	link.description = request.get('description')
	link.is_actual = request.get('is_actual') == '1' 
	link.put()
	
	_update_search_index(link, request.get('tags'))

	#saving tags
	for tag in LinkTag.all().filter('link = ', link):
		tag.delete()
	if request.get('tags'):
		tags = request.get('tags').split(',')
		for tag_name in tags:
			tag_name = tag_name.strip()
			if len(tag_name):
				tag = Tag.gql('where name=:1',tag_name).get()
				if tag == None:
					tag = Tag(name=tag_name).put()
				LinkTag(link=link, tag=tag, is_actual=link.is_actual, owner=link.owner).put()
			
	result['ok'] = 1
	return webapp2.Response(json.dumps(result), content_type='application/json')
	
def edit_item(request, *args, **kwargs):		
	params = {}
	params['item_id'] = request.get('item_id')
	if params['item_id']:
		link = Link.get(params['item_id'])
		link.tags = []
		for tag in LinkTag.all().filter('link = ', link).fetch(10):
			link.tags.append(tag.tag.name)
		params['link'] = link
	params['tags'] = Tag.all()
	return _render_to_response(params,'edit')


def delete_item(request, *args, **kwargs):
	result = {}
	if request.get('item_id'):
		result['item_id'] = request.get('item_id')
		link = Link.get(result['item_id'])
	if link:
		search.Index(name='links').delete(result['item_id'])
		for tag in LinkTag.all().filter('link = ', link):
			tag.delete()
		link.delete()
		result['ok'] = 1
		
	else:
		result['error'] = 1
	return webapp2.Response(json.dumps(result), content_type='application/json')

def expire_item(request, *args, **kwargs):
	result = {}
	if request.get('item_id'):
		result['item_id'] = request.get('item_id')
		link = Link.get(result['item_id'])
	if link:
		link.is_actual = False
		link.put()
		tags = []
		for tag in LinkTag.all().filter('link = ', link):
			tags.append(tag.tag.name)
		_update_search_index(link, ','.join(tags))
		result['ok'] = 1
		
	else:
		result['error'] = 1
	return webapp2.Response(json.dumps(result), content_type='application/json')

	
def search_links(request, *args, **kwargs):
	params = {}
	params['page'] = request.get('page')
	if request.get('make_search'):
		params['make_search'] = 1
		params['query'] = {}
		
		query_string = []
		query_string.append('owner = %s' % users.get_current_user().user_id())
		if request.get('text'):
			query_string.append('(link:"%s" OR description:"%s")' % (request.get('text'), request.get('text')))
			params['query']['text'] = request.get('text')
			
		if request.get('created'):
			params['query']['created'] = request.get('created')
			if request.get('created') == '1day':
				query_string.append('created > %s' % datetime.date.today())
			if request.get('created') == '1week':
				query_string.append('created > %s' % (datetime.date.today() - datetime.timedelta(days=7)))
			if request.get('created') == '1month':
				query_string.append('created > %s' % (datetime.date.today() - datetime.timedelta(days=30)))
			if request.get('created') == 'period':
				pass
				
		if request.get('show_not_actual'):
			params['query']['show_not_actual'] = request.get('show_not_actual')
		else:
			query_string.append('is_actual = 1')
		
		if request.get('tag'):
			params['query']['tag'] = request.get('tag')
			query_string.append('tags:"%s"' % request.get('tag'))
			
		search_index = search.Index(name='links')
		#print search_index
		#print query_string
		results = search_index.search(search.Query(
			query_string = ' AND '.join(query_string),
			options=search.QueryOptions(
				limit=20,
				#sort_options=search.SortOptions(
				#	expressions=[
				#		search.SortExpression(expression='created', direction=SortExpression.DESCENDING, #default_value='')],
				#	limit=1000),
				ids_only=True)))
		#for i,res in enumerate(results):
		#	print i, res

		params['keys'] = []
		for res in results:
			params['keys'].append(db.Key(res.doc_id))
	
	else:
		params['skip_get_list'] = 1
		
	params['tags'] = Tag.all()
	
	
	return _get_list_and_render(params, 'поиск', 'search')
	
def _update_search_index(link, tags):
	search_doc = search.Document(
		doc_id=str(link.key()),
        fields=[search.TextField(name='link', value=link.link),
                search.TextField(name='description', value=link.description),
				search.TextField(name='owner', value=link.owner),
                search.DateField(name='created', value=link.created),
				search.NumberField(name='is_actual', value=int(link.is_actual)),
				search.TextField(name='tags', value=tags)])
	search.Index(name='links').put(search_doc)
	return

def _get_list_and_render(params, page_title, template_name='list'):
	if params['page'] is None or not params['page'].isdigit() or params['page']<1:
		params['page'] = 1
	params['page'] = int(params['page'])
	if params.has_key('skip_get_list') == False:
		links = _get_list(params)
		params['links'] = links['list']
		params['total'] = links['total']
		params['pages'] = range(1, links['pages']+1)
	params['page_title'] = page_title
	params['menu_items'] = get_menu_items()
	params['user'] = users.get_current_user().nickname()
	
	return _render_to_response(params,template_name)

	
def _get_list(params):
	params['limit'] = 5
	q = db.Query(Link)
	q.filter('owner = ', users.get_current_user().user_id())
	
	if params.has_key('not_actual'):
		q.filter('is_actual =', False)
	else:
		q.filter('is_actual =', True)
	
	if params.has_key('year'):
		q.filter('created_year = ', params['year'])
	if params.has_key('month'):
		q.filter('created_month = ', params['month'])
	if params.has_key('day'):
		q.filter('created_day = ', params['day'])
		
	if params.has_key('tag'):
		linktags = []
		for lt in LinkTag.all().filter('tag = ', params['tag']):
			linktags.append(lt.link.key())
		q.filter('__key__ in ', linktags)

	if params.has_key('keys'):
		q.filter('__key__ in ', params['keys'])
		
	total = q.count()
	q.order('-created')
	links = q.fetch(limit=params['limit'], offset=(params['page']-1)*params['limit'])

	#for (i, link) in enumerate(links):
	for link in links:
		link.tags = LinkTag.all().filter('link = ', link).fetch(10)

	#for i,linktag in enumerate(LinkTag.all()):
	#	print i, linktag.key(), linktag.link.key(), linktag.tag.key()
	#	logging.info('%s %s', linktag.link.key(), linktag.tag.name)
	return {'list': links, 'total': total, 'pages': int(math.ceil(total/params['limit']))}

	
def _render_to_response(params, template_name, status=200):
	path = os.path.join(os.path.dirname(__file__), 'templates', '%s.html' % template_name)
	return webapp2.Response(template.render(path, params), status=status)

	
def get_menu_items():
	items = []
	items.append({'name': 'главная', 'url': '/'})
	items.append({'name': 'тэги', 'url': '/tags/'})
	items.append({'name': 'устаревшие', 'url': '/list/old/'})
	items.append({'name': 'добавить', 'url': '#', 'class': 'open_edit_form'})
	items.append({'name': 'поиск', 'url': '/search/'})
	return items
	
def _404():
	return _render_to_response({}, '404', 404)
	
def handle_404(request, response, exception):
	logging.exception(exception)
	return _404()
	
app = webapp2.WSGIApplication([
	#/list/2012/06/07/ /list/2012/06/ /list/2012/
	webapp2.Route('/list/<year:\d{4}>/<month:\d{2}>/<day:\d{2}>/', show_list),
	webapp2.Route('/list/<year:\d{4}>/<month:\d{2}>/', show_list),
	webapp2.Route('/list/<year:\d{4}>/', show_list),
	#/tag/tag1/
	webapp2.Route('/tag/<tag>/', show_list_by_tag),
	webapp2.Route('/tags/', show_tags_list),
	webapp2.Route('/list/old/', show_list_not_actual),
	webapp2.Route('/search/', search_links),
	
	webapp2.Route('/save/', save_item),
	webapp2.Route('/edit/', edit_item),
	webapp2.Route('/delete/', delete_item),
	webapp2.Route('/expire/', expire_item),
	webapp2.Route('/', show_index),
	
], debug=True)

app.error_handlers[404] = handle_404