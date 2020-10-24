#!/usr/bin/env python3
import os
import json         # parsing json files
import datetime     # time and dates functions
import pytz         # timestamp localization / timezones
import requests     # http and api calls library
from .update_state import update_state

import singer
from singer import utils, metadata
from singer.catalog import Catalog, CatalogEntry
from singer.schema import Schema

# For dumb testing - delete this function later
def whatisthis(item):
        try:
            item_name = item.__name__
        except:
            item_name = "THIS ITEM"
        print('\n',item,'\n'+ item_name +' IS TYPE: ',type(item),'\n')

fake_p_text =  {"status":"REQUEST_SUCCEEDED","responseTime":236,"message":["No Data Available for Series BDS0000000000000000110901LQ5 Year: 2020"],"Results":{
"series":
[{"seriesID":"IAMAFAKETHINGAMEBOB","data":[{"year":"1234","period":"Q02","periodName":"2nd Quarter","value":"1179","footnotes":[{}],"calculations":{"net_changes":{"3":"22","6":"-102","12":"-59"},"pct_changes":{"3":"1.9","6":"-8.0","12":"-4.8"}}},{"year":"4567","period":"Q01","periodName":"1st Quarter","value":"1157","footnotes":[{}],"calculations":{"net_changes":{"3":"-124","6":"-39","12":"102"},"pct_changes":{"3":"-9.7","6":"-3.3","12":"9.7"}}}]}]
}}

REQUIRED_CONFIG_KEYS = ["calculations", "user-id", "api-key", "startyear", "endyear"]
LOGGER = singer.get_logger()
now = datetime.datetime.now()

# function for finding a file on the system running the tap, relative to the file running the tap.
def get_abs_path(path):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

# go into the local 'schemas' folder, and pare through all the .json files you find there.
def load_schemas():
    ### Load schemas from schemas folder ###
    schemas = {}
    for filename in os.listdir(get_abs_path('schemas')):
        path = get_abs_path('schemas') + '/' + filename
        file_raw = filename.replace('.json', '')
        with open(path) as file:
            schemas[file_raw] = Schema.from_dict(json.load(file))
    return schemas  # returns as object type 'dict'

def discover():
    raw_schemas = load_schemas()
    streams = []
    for stream_id, schema in raw_schemas.items():
        # TODO: populate any metadata and stream's key properties here..
        stream_metadata = [{"metadata":{"inclusion":"available","selected":"true"},"breadcrumb":[]}]
        key_properties = ["year"]
        rep_key = ["year"]
        rep_method = None
        streams.append(
            CatalogEntry(
                tap_stream_id=stream_id,
                stream=stream_id,
                key_properties=key_properties,
                metadata=stream_metadata,
                replication_key=rep_key,
                is_view=None,
                database=None,
                table=None,
                row_count=None,
                stream_alias=None,
                replication_method=rep_method,
                schema=schema    
            )
        )
    return Catalog(streams) # object with class 'singer.catalog.Catalog'

def sync(config, state, catalog):
    
    # whatisthis(state)
    
    """ Sync data from tap source """        
    # Loop over selected streams in catalog
    # pickup_year is the most recent year value in the STATE file
    
    for stream in catalog.get_selected_streams(state):
        # whatisthis(state["bookmarks"].keys())

        if stream.stream in state["bookmarks"].keys():
            try:
                pickup_year = int(state["bookmarks"][stream.stream]['year'])
            except:
                start_year = False
                year_reset = "There was an error with the year format \""+ state[stream.stream] +"\" in the State file for stream " + str(stream.stream)
                LOGGER.info(year_reset)
            else:
                start_year = int(config['startyear'])
                if (start_year < pickup_year and pickup_year <= now.year):
                    config['startyear'] = str(pickup_year)
                    year_reset = "As per state, resetting start year for stream " + str(stream.stream) + " to " + config['startyear']
                    LOGGER.info(year_reset)
                
        LOGGER.info("Syncing stream:" + stream.tap_stream_id)
        
        bookmark_column = stream.replication_key
        
        is_sorted = False  # TODO: indicate whether data is sorted ascending on bookmark value

        # print('\nSTREAM ID: ',stream.tap_stream_id,'\n')
        # print('\nSCHEMA: ',stream.schema,'\n')
        # print('\nKEY PROPERTIES: ',stream.key_properties,'\n')

        singer.write_schema(
            stream_name=stream.tap_stream_id,
            schema=stream.schema.to_dict(), #the to_dict() bit is a change to the cookiecutter template.
            key_properties=stream.key_properties,
        )

        ####  SUPER MANUAL CALL STARTS HERE ####       
                
        def call_api(catalog):
            headers = {'Content-type': 'application/json'}
            data = json.dumps(catalog)
            p = requests.post('https://api.bls.gov/publicAPI/v2/timeseries/data/', data=data, headers=headers)
                  
            # return(fake_p_text)
            return json.loads(p.text)
        
        fetched_series = [stream.tap_stream_id]
        
        api_variables = {"seriesid": fetched_series,"startyear":config['startyear'], "endyear":config['endyear'],"calculations":config['calculations'],"registrationkey":config['api-key']}
        
        json_data = call_api(api_variables)
        
        # print('\nLine 84: ',json_data)
        
        ####  End the API call
        max_bookmark = 0
        max_year = 0
        utc = pytz.timezone('UTC')
        thetime = utc.localize(datetime.datetime.now())
        thetimeformatted = thetime.astimezone().isoformat()
        
        for series in json_data['Results']['series']:
        
        
            seriesId = series['seriesID']                
            time_extracted = utc.localize(datetime.datetime.now()).astimezone().isoformat()
        
            for item in series['data']:
                year = item['year']
                if max_year < int(year):
                    max_year = int(year)
                period = item['period']
                if period[0] == 'M':
                    month = int(period[1]+period[2])
                    quarter = round((int(period[1]+period[2])/3)+0.3)
                elif period[0] == 'Q':
                    month = 0
                    quarter = period[2]
                else:
                    month = ""
                    quater= ""
                value = item['value']
                full_period = str(year) + "-" + str("{0:0=2d}".format(month)) + "-01T00:00:00-04:00"
                footnotes=""
                for footnote in item['footnotes']:
                    if footnote:
                        footnotes = footnotes + footnote['text'] + ','

                next_row = {
                    "type":"RECORD",
                    "stream": seriesId,
                    "time_extracted": time_extracted,
                    "schema":seriesId,
                    "record":{
                        "SeriesID": seriesId,
                        "year": year,
                        "period": period,
                        "value": value,
                        "footnotes":footnotes[0:-1],
                        "month": str(month),
                        "quarter":str(quarter),
                        "time_extracted":time_extracted,
                        "full_period":full_period
                        }
                    }
        
                # write one or more rows to the stream:
                singer.write_records(stream.tap_stream_id,[next_row])
                # capture stream state
                if bookmark_column:
                    
                    if is_sorted:
                        # update bookmark to latest value - this is redundant for tap-bls
                        singer.write_state({stream.tap_stream_id: next_row["record"][bookmark_column[0]]})
                    else:
                        # if data unsorted, save max value until end of writes.  tap-bls goes by the year and will use this approach
                        max_bookmark = max(max_bookmark, int(next_row["record"][bookmark_column[0]]))
        if bookmark_column and not is_sorted:
            singer.write_state({stream.tap_stream_id: max_bookmark})
            if config['update_state'].lower() == 'true':  # if you set 'uptadate_state' in config.json the *tap* will update the STATE file - note this is NOT standard behaviour in Singer data flows as the *target* should handle STATE updates.
                LOGGER.info(update_state({stream.tap_stream_id: max_bookmark}))
    return

@utils.handle_top_exception(LOGGER)  # decorates main with exception logging 
def main():
    # Parse command line arguments
    args = utils.parse_args(REQUIRED_CONFIG_KEYS)

    # If discover flag was passed, run discovery mode and dump output to stdout
    if args.discover:
        catalog = discover()
        catalog.dump()
    # Otherwise run in sync mode
    else:
        if args.catalog:
            catalog = args.catalog
        else:
            catalog = discover()
            
        sync(args.config, args.state, catalog)

# if this file is being called as the main program, execute the function main().
if __name__ == "__main__":
    main()