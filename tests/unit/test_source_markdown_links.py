# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import PurePosixPath


def test_reads_each_link_target_that_names_a_path_on_its_line() -> None:
    text = (
        "# Intro\n"
        'See [setup](setup.md) and ![the flow](images/flow.png "Flow").\n'
        "[Amended: [the module](../src/pkg/module.py#L3) and its\n"
        "[`records`](records/) say why.]\n"
        "Not paths: [a URL](https://example.org/guide/setup.md), [mail](mailto:team@example.org),\n"
        "[a host](//example.org/setup.md), [a heading](#intro) and [nothing]().\n"
    )

    links = _links_in(PurePosixPath("guide/intro.md"), text)

    assert [str(link) for link in links] == [
        "guide/intro.md:2: setup.md",
        "guide/intro.md:2: images/flow.png",
        "guide/intro.md:3: ../src/pkg/module.py#L3",
        "guide/intro.md:4: records/",
    ]
