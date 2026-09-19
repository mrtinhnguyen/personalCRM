from app.profile_presentation import identity_key, present_identities, presentation


def test_linkedin_fields_are_not_accounts_and_url_alias_is_one_account():
    assert identity_key('linkedin','26 Aug 2023','26 Aug 2023') is None
    assert identity_key('linkedin','Pittsburgh, Pennsylvania, United States') is None
    rows=[{'id':str(i),'provider':'linkedin','external_id':key,'profile_url':url}
          for i,(key,url) in enumerate([('han-bao','https://www.linkedin.com/in/han-bao/'),
              ('https://www.linkedin.com/in/han-bao','https://www.linkedin.com/in/han-bao'),('26 Aug 2023','26 Aug 2023')])]
    assert len(present_identities(rows))==1
    assert identity_key('linkedin','https://evil-linkedin.com/in/alice') is None


def test_profile_bios_preserve_platforms_and_deduplicate_only_equal_facts():
    fields=[{'field_key':'monica.custom_fields','value':{'LinkedIn About':['A\\nB'],'微信个性签名':['微信简介'],'Instagram 简介':['照片简介']}},
            {'field_key':'linkedin.about','value':'A\nB'}]
    base={'fact_type':'employment','current_source_type':'linkedin','company_name':'Company','school_name':None}
    facts=[{**base,'value':{'title':'Engineer','start_date':'2020'}},{**base,'value':{'title':'Engineer','start_date':'2020'}},{**base,'value':{'title':'Engineer','start_date':'2024'}}]
    out=presentation(fields,facts)
    assert out['sources']['linkedin']['about']=='A\nB'
    assert out['sources']['instagram']['biography']=='照片简介'
    assert out['sources']['wechat']['signature']=='微信简介'
    assert len(out['facts'])==2


def test_source_coordinates_reverse_only_chatlog_xml_slots():
    from app.main import _build_location_summary, _location_point

    for raw,expected in [
        ({'latitude':'7.61780024','longitude':'47.4845009'},(47.4845009,7.61780024)),
        ({'latitude':'-4.15626383','longitude':'55.9204254'},(55.9204254,-4.15626383)),
        ({'latitude':'-122.4194','longitude':'37.7749'},(37.7749,-122.4194)),
        ({'latitude':'121.471212','longitude':'31.152393'},(31.152393,121.471212)),
    ]:
        assert _location_point(raw,'chatlog_sns_xml')==expected
    assert _location_point({'lat':47.4845,'lon':7.6178})==(47.4845,7.6178)
    assert _location_point({'latitude':37.7749,'longitude':-122.4194})==(37.7749,-122.4194)
    assert _location_point({'latitude':0,'longitude':0},'chatlog_sns_xml') is None
    points=_build_location_summary([{'provider':'wechat','location':{'latitude':'7.61780024','longitude':'47.4845009','poiName':'Dornach'},'coordinate_format':'chatlog_sns_xml'}])
    assert 'mlat=47.4845009&mlon=7.61780024' in points[0]['map_url']


def test_legacy_graph_indexes_are_never_imported_as_wechat_accounts(tmp_path,monkeypatch):
    import json

    from app.full_migration import load_moments_and_relationships
    (tmp_path/'moments_graph.json').write_text(json.dumps({'nodes':[],'edges':[{'a':418,'b':372,'like':7}]}))
    class Database:
        def commit(self):pass
    monkeypatch.setattr('app.full_migration.add_relation',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Graph index became a person relationship')))
    load_moments_and_relationships(Database(),tmp_path,{'418':'person_a','372':'person_b'})


def test_city_reference_does_not_guess_ambiguous_or_country_only_locations():
    from app.location_atlas import resolve_city
    assert resolve_city('Springfield','US') is None
    assert resolve_city('United States') is None
    assert resolve_city('San Francisco Bay Area') is None
    pittsburgh=resolve_city('Pittsburgh, Pennsylvania, United States')
    assert 40<pittsburgh['latitude']<41 and -80<pittsburgh['longitude']<-79
    assert resolve_city('芝加哥','US','Illinois')['geoname_id']==4887398


def test_instagram_mobile_archive_location_is_retained_without_transposing():
    from app.main import _location_point
    from app.reconcile_sources import instagram_location
    location=instagram_location({'location':None,'iphone_struct':{'location':{'name':'San Jose','lat':37.3293048,'lng':-121.8875475,'profile_pic_url':None}}})
    assert location=={'name':'San Jose','lat':37.3293048,'lng':-121.8875475}
    assert _location_point(location)==(37.3293048,-121.8875475)
