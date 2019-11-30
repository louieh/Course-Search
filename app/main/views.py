from flask import render_template, session, redirect, url_for, jsonify, request, abort
from flask import current_app
from . import main
from pymongo import MongoClient
import re
import datetime
import json
import requests
import redis


def getDataupdatetime():
    try:
        redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        data_update_time = redis_client.get(REDIS_UPDATE_TIME_KEY)
        data_update_next_time = redis_client.get(REDIS_UPDATE_NEXT_TIME_KEY)
    except:
        return None
    return data_update_time, data_update_next_time


def getRateId(name):
    rateuri = "https://search-production.ratemyprofessors.com/solr/rmp/select/?rows=20&wt=json&q=" + name + "&defType=edismax&qf=teacherfirstname_t%5E2000+teacherlastname_t%5E2000+teacherfullname_t%5E2000+autosuggest&group.limit=50"
    try:
        resp = requests.get(rateuri)
    except:
        return None, 'downloadfail'
    try:
        resp_parse = json.loads(resp.text)
        resp_parse_list = resp_parse.get('response').get('docs')
        for each_resp in resp_parse_list:
            if 'University of Texas at Dallas' in each_resp.get("schoolname_s"):
                return each_resp.get('pk_id'), 'ok'
        return None, 'notfound'
    except:
        return None, 'parsefail'


@main.before_app_first_request
def before_first_request():
    global TIMEDELTA, collection, db, REDIS_HOST, REDIS_PORT, REDIS_UPDATE_TIME_KEY, REDIS_UPDATE_NEXT_TIME_KEY, TERM_LIST
    TIMEDELTA = current_app.config.get('TIMEDELTA')
    TERM_LIST = current_app.config.get('TERM_LIST')
    session['DATA_SOURCE'] = TERM_LIST[0]  # first term
    REDIS_UPDATE_TIME_KEY = current_app.config.get('REDIS_UPDATE_TIME_KEY')
    REDIS_UPDATE_NEXT_TIME_KEY = current_app.config.get('REDIS_UPDATE_NEXT_TIME_KEY')
    MONGO_HOST = current_app.config.get('MONGO_HOST')
    MONGO_PORT = current_app.config.get('MONGO_PORT')
    REDIS_HOST = current_app.config.get('REDIS_HOST')
    REDIS_PORT = current_app.config.get('REDIS_PORT')
    client = MongoClient(MONGO_HOST, MONGO_PORT)
    db = client.Coursebook
    collection = db.CourseForSearch


@main.route('/login', methods=['GET', 'POST'])
def login():
    return render_template('login.html')


@main.route('/findrate/<name>')
def findrate(name):
    pk_id, reason = getRateId(name)
    if not pk_id:
        # logging.INFO(reason)
        return redirect('http://www.ratemyprofessors.com/search.jsp?query=%s' % name)

    return redirect('http://www.ratemyprofessors.com/ShowRatings.jsp?tid=%s' % pk_id)


@main.route('/changesource/<source>')
def changesource(source):
    session['DATA_SOURCE'] = source
    data = list(collection.find({"class_term": source}, {"_id": 0}))
    return jsonify(data)


@main.route('/', methods=['GET', 'POST'])
def search():
    term = session.get("DATA_SOURCE", TERM_LIST[0])  # get term first

    item_list = ["class_title", "class_number", "class_section", "class_instructor",
                 "class_day", "class_start_time",
                 "class_end_time", "class_location"]  # "class_term", "class_status" 非前端筛选条件

    abbr_dict = {
        'ai': 'Artificial Intelligence',
        'ml': 'Machine Learning',
        'nlp': 'Natural Language Processing',
        'ca': 'Computer Architecture',
        'os': 'Operating System',
        'hci': 'Human Computer Interactions',
        'vr': 'Virtual Reality',
        'aos': 'Advanced Operating Systems',
    }

    item_dict = session.get('item_dict')
    if not item_dict:
        item_dict = {}
    item_dict_result = {}
    item_dict_result["class_term"] = term

    if request.method == 'POST':
        for each_item in item_list:
            if each_item in request.form and request.form[each_item]:
                item_dict[each_item] = request.form[each_item]
        if "class_title" in item_dict.keys():  # update class title based on addr dict
            if item_dict.get("class_title").lower() in abbr_dict.keys():
                item_dict.update(class_title=abbr_dict.get(item_dict.get("class_title").lower()))
        fuzzyquery = 1 if "fuzzyquery" in request.form else 0

        session['item_dict'] = item_dict
        session['fuzzyquery'] = fuzzyquery
        session['button'] = 'nowclass' if 'nowclass' in request.form else 'search'
        return redirect(url_for('main.search'))

    if item_dict and session.get('button') == 'search':
        if session.get('fuzzyquery'):
            for eachKey in item_dict.keys():
                item_dict_result[eachKey] = re.compile(str(item_dict.get(eachKey)), re.I)
        else:
            item_dict_result = item_dict
    elif session.get('button') == 'nowclass':
        if "class_location" in item_dict.keys():
            if session.get('fuzzyquery'):
                item_dict_result['class_location'] = re.compile(str(item_dict.get("class_location")), re.I)
            else:
                item_dict_result['class_location'] = item_dict.get('class_location')
        if "class_instructor" in item_dict.keys():
            if session.get('fuzzyquery'):
                item_dict_result['class_instructor'] = re.compile(str(item_dict.get("class_instructor")), re.I)
            else:
                item_dict_result['class_instructor'] = item_dict.get('class_instructor')
        time_now_all = (datetime.datetime.utcnow() - datetime.timedelta(hours=TIMEDELTA)).strftime('%A-%H:%M')
        week_now, time_now = time_now_all.split('-')
        item_dict_result['class_day'] = re.compile(week_now, re.I)
        item_dict_result['class_start_time'] = {"$lte": time_now}
        item_dict_result['class_end_time'] = {"$gte": time_now}

    courses_list = list(collection.find(item_dict_result, {"_id": 0}))
    count = len(courses_list)

    session['item_dict'] = None
    session['fuzzyquery'] = None
    session['button'] = None
    data_update_time, data_update_next_time = getDataupdatetime()
    if data_update_time or data_update_next_time:
        if data_update_time:
            data_update_time = datetime.datetime.strptime(data_update_time, "%Y-%m-%d %H:%M")
        if data_update_next_time:
            data_update_next_time = datetime.datetime.strptime(data_update_next_time, "%Y-%m-%d %H:%M")

    return render_template('search.html', data=courses_list, Filter=item_dict,
                           data_update_time=data_update_time, data_update_next_time=data_update_next_time)


@main.route('/graph/professor/')
@main.route('/graph/professor/<professor>')
@main.route('/graph/course')
@main.route('/graph/course/<coursesection>')
@main.route('/graph/speed')
@main.route('/graph/speed/<term_num>')
def graph_pro(professor=None, coursesection=None, term_num=None):
    if not professor and not coursesection and not term_num:
        # TODO Sort by last name
        if "graph/professor" in request.url:
            professor_set = set()
            professor_dict_list = list(db.CourseForGraph.find({}, {"class_instructor": 1, "_id": 0}))
            for eachdict in professor_dict_list:
                for each in eachdict.get("class_instructor"):
                    if "Staff" not in each:
                        professor_set.add(each)
            professor_char_dict = {}
            for i in range(65, 91):  # use alphabet as key
                professor_char_dict[chr(i)] = []
            for each_professor_name in professor_set:  # insert professor name to professor_char_dict based on the first letter of their name
                professor_char_dict[each_professor_name[0]].append(each_professor_name)
            professor_list_list = []
            for eachkey in professor_char_dict.keys():  # insert the key_value of professor_char_dict to a new list
                if professor_char_dict.get(eachkey):
                    professor_list_list.append([eachkey] + professor_char_dict.get(eachkey))
            return render_template("graph.html", professor_list_list=professor_list_list)
        elif "graph/course" in request.url:
            cou_set = set()
            cou_dict_list_fin = []
            cou_dict_list = list(db.CourseForGraph.find({}, {"class_title": 1, "class_section": 1, "_id": 0}))
            for eachcou_dict in cou_dict_list:
                eachcou_dict["class_section"] = eachcou_dict.get("class_section").split(".")[0]
                if eachcou_dict["class_section"] not in cou_set:
                    cou_set.add(eachcou_dict["class_section"])
                    cou_dict_list_fin.append(eachcou_dict)
            return render_template("graph.html", cou_dict_list=cou_dict_list_fin)
        elif "graph/speed" in request.url:
            speed_dict_list = list(
                db.CourseForSpeed.find({}, {"_id": 0, "class_day": 0, "class_start_time": 0, "update_data": 0}))
            return render_template("graph.html", speed_dict_list=speed_dict_list)

    if term_num:
        term, num = term_num.split("_")
        speed_data = list(db.CourseForSpeed.find({"class_term": term, "class_number": num}, {"_id": 0}))
        if not speed_data:
            abort(404)
        if len(speed_data) > 1:
            print("len(speed_data) > 1")
        speed_data = speed_data[0]

        def trans_utd(timestamp):
            utc_time = (datetime.datetime.utcfromtimestamp(timestamp) - datetime.timedelta(hours=TIMEDELTA)).strftime(
                "%Y-%m-%d %H:%M")
            return utc_time

        x_data = [trans_utd(each.get("timestamp")) for each in speed_data.get("update_data")]
        y_data = [each.get("percentage") * 100 for each in speed_data.get("update_data")]
        return render_template('graph.html', x_data=x_data, y_data=y_data,
                               class_term=term,
                               class_title=speed_data.get("class_title"),
                               class_section=speed_data.get("class_section"),
                               class_instructor=speed_data.get("class_instructor")
                               )

    if professor:
        if not list(db.CourseForGraph.find({"class_instructor": professor})):
            abort(404)

        term_dict_list = []
        for eachterm in TERM_LIST:
            term_dict = {}
            course_dict_list = []
            all_course_list = list(
                db.CourseForGraph.find({"class_term": eachterm, "class_instructor": professor}, {"_id": 0}))
            if all_course_list:
                for eachcourse in all_course_list:
                    course_dict = {}
                    course_dict["name"] = eachcourse.get("class_title")
                    course_dict["value"] = eachcourse.get("class_section").split(" ")[-1].split(".")[0]
                    course_dict_list.append(course_dict)
            term_dict["name"] = eachterm
            term_dict["children"] = course_dict_list
            term_dict_list.append(term_dict)
        professor_json = {"name": professor, "children": term_dict_list}
        return render_template('graph.html', professor_name=professor,
                               professor_json=professor_json)
    if coursesection:
        all_course_list = list(db.CourseForGraph.find({"class_section": {"$regex": coursesection}}, {"_id": 0}))
        if not all_course_list:
            abort(404)
        else:
            course_name = all_course_list[0].get("class_title")

        term_dict = {}
        for eachterm in TERM_LIST:
            term_dict[eachterm] = []

        for eachcourse_dict in all_course_list:
            professorname_list = eachcourse_dict.get("class_instructor")
            term = eachcourse_dict.get("class_term")
            for eachprofessorname in professorname_list:
                temp_professorname_dict = {"name": eachprofessorname, "value": eachprofessorname}
                if not temp_professorname_dict in term_dict[term]:
                    term_dict[term].append(temp_professorname_dict)

        final_list = []
        for eachterm in TERM_LIST:
            temp_final_dict = {"name": eachterm, "children": term_dict.get(eachterm)}
            final_list.append(temp_final_dict)
        final_dict = {"name": coursesection, "children": final_list}
        return render_template('graph.html', course_section=coursesection.lower().replace(' ', ''),
                               course_name=course_name,
                               course_json=final_dict)


@main.route('/comments/<professor>')
def comments(professor):
    if not professor:
        abort(404)
    courses = list(
        db.CourseForGraph.find({"class_instructor": professor}, {"_id": 0, "class_term": 0, "class_instructor": 0}))
    section_set = set()
    title_set = set()
    section_title_set = set()
    for course in courses:
        section = course.get("class_section").split(".")[0]
        title = course.get("class_title")
        if section not in section_set and title not in title_set:
            section_set.add(section)
            title_set.add(title)
            section_title_set.add(section + "-" + title)
    return render_template('comments.html', section_title_list=list(section_title_set))


@main.route('/jobinfo')
def jobinfo():
    job_filter, num = get_jobinfo_args()
    if db.JobInfo.find(job_filter).count() - num <= 10:
        return render_template('jobinfo.html')
    else:
        data = db.JobInfo.find(job_filter, {'_id': 0, 'name': 1, 'company': 1, 'city': 1, 'create_time': 1}).sort(
            [{'create_time', -1}]).skip(num).limit(10)

        return render_template('jobinfo.html', data=list(data), job_filter=job_filter)


def get_jobinfo_args():
    job_filter = {}

    city_index = request.args.get('city')
    city = city_dict.get(city_index)
    if city:
        job_filter['city'] = city

    firm_index = request.args.get('firm')
    firm = firm_dict.get(firm_index)
    if firm:
        job_filter['company'] = firm

    num = request.args.get('num')
    if not num:
        num = 0
    else:
        num = int(num)
    return job_filter, num


@main.route('/jobinfodata')
def jobinfodata():
    job_filter, num = get_jobinfo_args()

    data = db.JobInfo.find(job_filter, {'_id': 0, 'name': 1, 'company': 1, 'city': 1, 'create_time': 1}).sort(
        [{'create_time', -1}]).skip(num).limit(10)
    ifnext = not db.JobInfo.find(job_filter).count() - num <= 10
    ifpre = num > 0
    result = {'data': list(data), 'ifnext': ifnext, 'ifpre': ifpre}
    return jsonify(result)


city_dict = {
    '1': '北京',
    '2': '上海',
    '3': '杭州',
    '4': '深圳',
    '5': '武汉',
}

firm_dict = {
    '1': 'bytedance',
    '2': 'baidu',
    '3': 'bilibili',
}
