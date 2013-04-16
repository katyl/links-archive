from google.appengine.ext import db

class Link(db.Model):
	#link = db.StringProperty()
	link = db.LinkProperty()
	description = db.StringProperty()
	created = db.DateTimeProperty(auto_now_add=True)
	created_day = db.IntegerProperty()
	created_month = db.IntegerProperty()
	created_year = db.IntegerProperty()
	is_actual = db.BooleanProperty()
	owner = db.StringProperty()

	def __unicode__(self):
		return "[%s] %s (%s)" % (self.key(), self.link, self.created)

class Tag(db.Model):
	name = db.StringProperty()

	def __unicode__(self):
		return self.name
			
class LinkTag(db.Model):
	link = db.ReferenceProperty(Link, required=True, collection_name='links')
	tag = db.ReferenceProperty(Tag, required=True, collection_name='tags')
	is_actual = db.BooleanProperty()
	owner = db.StringProperty()
	