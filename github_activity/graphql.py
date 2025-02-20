import os
import requests
from datetime import timedelta

import numpy as np
import pandas as pd
from IPython.display import display
from ipywidgets import widgets

comments_query = """\
        comments(last: 100) {
          edges {
            node {
              authorAssociation
              createdAt
              updatedAt
              url
              author {
                login
              }
            }
          }
        }
"""

base_elements = """\
        state
        id
        title
        url
        createdAt
        updatedAt
        closedAt
        labels(first: 10) {
            edges {
                node {
                    name
                }
            }
        }
        number
        authorAssociation
        author {
          login
        }
"""

gql_template = """\
{{
  search({query}) {{
    issueCount
    pageInfo {{
        endCursor
        hasNextPage
    }}
    nodes {{
      ... on PullRequest {{
        {base_elements}
        mergedBy {{
          login
        }}
        mergeCommit {{
          oid
        }}
        {comments}
      }}
      ... on Issue {{
        {base_elements}
        {comments}
      }}
    }}
  }}
}}
"""

# Define our query object that we'll re-use for github search
class GitHubGraphQlQuery():
    def __init__(self, query, display_progress=True, auth=None):
        """Run a GitHub GraphQL query and return the issue/PR data from it.

        Parameters
        ----------
        query : string
          The GitHub search query to run. This is similar to whatever you'd use
          to search on GitHub.com.
        display_progress : bool
          Whether to display a progress bar as data is fetched.
        auth : string | None
          An authentication token for GitHub. If None, then the environment
          variable `GITHUB_ACCESS_TOKEN` will be tried.
        """
        self.query = query

        # Authentication
        headers = {}
        auth = os.environ.get('GITHUB_ACCESS_TOKEN') if auth is None else auth
        if auth is not None:
            headers.update({"Authorization": "Bearer %s" % auth})

        self.headers = headers
        self.gql_template = gql_template
        self.display_progress = display_progress

    def request(self, n_pages=100, n_per_page=50):
        """Make a request to the GitHub GraphQL API.

        This generates an attribute `self.data` with a pandas
        DataFrame of the issue / PR activity corresponding to
        the query you ran.
        """

        # NOTE: This main search query has a type, but the query string also has a type.
        # ref ("search"): https://developer.github.com/v4/query/#connections
        # Collect paginated issues
        self.issues_and_or_prs = []
        for ii in range(n_pages):
            github_search_query = [
                'first: %s' % n_per_page,
                'query: "%s"' % self.query,
                'type: ISSUE',
            ]
            if ii != 0:
                github_search_query.append('after: "%s"' % pageInfo['endCursor'])

            ii_gql_query = self.gql_template.format(
                query=', '.join(github_search_query),
                comments=comments_query,
                base_elements=base_elements,
            )
            ii_request = requests.post('https://api.github.com/graphql', json={'query': ii_gql_query}, headers=self.headers)
            if ii_request.status_code != 200:
                raise Exception("Query failed to run by returning code of {}. {}".format(ii_request.status_code, ii_gql_query))
            if "errors" in ii_request.json().keys():
                raise Exception("Query failed to run with error {}. {}".format(ii_request.json()['errors'], ii_gql_query))
            self.last_request = ii_request

            # Parse the response for this pagination
            json = ii_request.json()['data']['search']
            if ii == 0:
                if json['issueCount'] == 0:
                    print("Found no entries for query.")
                    self.data = pd.DataFrame()
                    return

                n_pages = int(np.ceil(json['issueCount'] / n_per_page))
                print("Found {} items, which will take {} pages".format(json['issueCount'], n_pages))
                prog = widgets.IntProgress(
                    value=0,
                    min=0,
                    max=n_pages,
                    description='Downloading:',
                    bar_style='',
                )
                if n_pages > 1 and self.display_progress:
                    display(prog)

            # Add the JSON to the raw data list
            self.issues_and_or_prs.extend(json['nodes'])
            pageInfo = json['pageInfo']
            self.last_query = ii_gql_query

            # Update progress and should we stop?
            prog.value += 1
            if pageInfo['hasNextPage'] is False:
                prog.bar_style = 'success'
                break

        # Create a dataframe of the issues and/or PRs
        self.data = pd.DataFrame(self.issues_and_or_prs)

        # Add some extra fields
        self.data['author'] = self.data['author'].map(lambda a: a['login'] if a is not None else a)
        self.data['org'] = self.data['url'].map(lambda a: a.split('/')[3])
        self.data['repo'] = self.data['url'].map(lambda a: a.split('/')[4])
